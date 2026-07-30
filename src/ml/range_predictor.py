"""Load active range regressors and produce predicted high/low bands.

Used by predict_today.py to augment news-driven + XGBoost picks with price
target bands (entry target high, stop-loss low).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import desc, select

from ..common.logger import get_logger
from ..db.models import ModelVersion
from ..db.session import get_session
from ..features.assembler import build_feature_matrix
from .range_regressor import RangeRegressor

logger = get_logger(__name__)


@dataclass
class RangeBundle:
    high_regressor: RangeRegressor
    low_regressor: RangeRegressor
    high_version: str
    low_version: str


def load_active_range_models() -> RangeBundle | None:
    """Load the active high/low range regressors. Returns None if either missing."""
    with get_session() as s:
        high_mv = s.scalar(
            select(ModelVersion)
            .where(
                ModelVersion.model_name == "range_high_regressor",
                ModelVersion.is_active.is_(True),
            )
            .order_by(desc(ModelVersion.trained_at))
        )
        low_mv = s.scalar(
            select(ModelVersion)
            .where(
                ModelVersion.model_name == "range_low_regressor",
                ModelVersion.is_active.is_(True),
            )
            .order_by(desc(ModelVersion.trained_at))
        )
        if high_mv:
            s.expunge(high_mv)
        if low_mv:
            s.expunge(low_mv)

    if high_mv is None or low_mv is None:
        logger.warning("range_models_missing")
        return None

    if not (high_mv.file_path and Path(high_mv.file_path).exists()):
        logger.warning("range_high_file_missing", path=high_mv.file_path)
        return None
    if not (low_mv.file_path and Path(low_mv.file_path).exists()):
        logger.warning("range_low_file_missing", path=low_mv.file_path)
        return None

    return RangeBundle(
        high_regressor=RangeRegressor.load(high_mv.file_path),
        low_regressor=RangeRegressor.load(low_mv.file_path),
        high_version=high_mv.version,
        low_version=low_mv.version,
    )


def predict_ranges_for_stocks(
    stock_ids: list[int],
    feature_date: date,
    bundle: RangeBundle | None = None,
    features_df: pd.DataFrame | None = None,
) -> dict[int, dict]:
    """Return {stock_id: {predicted_high_pct, predicted_low_pct}} for given stocks.

    If features_df is provided, uses it; otherwise builds a small window
    ending at feature_date.
    """
    if not stock_ids:
        return {}

    if bundle is None:
        bundle = load_active_range_models()
    if bundle is None:
        return {}

    # Load features if not provided
    if features_df is None or features_df.empty:
        features_df = build_feature_matrix(
            feature_date - timedelta(days=7),
            feature_date,
            write_parquet=False,
        )

    features_df = features_df.copy()
    features_df["trade_date"] = pd.to_datetime(features_df["trade_date"])
    latest = features_df[features_df["trade_date"] == pd.Timestamp(feature_date)]
    latest = latest[latest["stock_id"].isin(stock_ids)].copy()
    if latest.empty:
        return {}

    # Drop stocks with any missing feature
    required = bundle.high_regressor.feature_names
    complete_mask = latest[required].notna().all(axis=1)
    latest = latest[complete_mask]
    if latest.empty:
        return {}

    X = latest[required]
    high_preds = bundle.high_regressor.predict(X)
    low_preds = bundle.low_regressor.predict(X)

    result: dict[int, dict] = {}
    for i, (_, row) in enumerate(latest.iterrows()):
        sid = int(row["stock_id"])
        # Ensure signs are physically correct: high >= 0, low <= 0
        high_pct = max(0.0, float(high_preds[i]))
        low_pct = min(0.0, float(low_preds[i]))
        result[sid] = {
            "predicted_high_pct": high_pct,
            "predicted_low_pct": low_pct,
            "predicted_range_pct": high_pct - low_pct,
        }
    return result
