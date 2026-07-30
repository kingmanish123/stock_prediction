"""Label (target) generation for supervised learning.

Task formulation: at the close of `trade_date`, predict what will happen on the
NEXT trading day (`trade_date+1` per stock's calendar).

Targets computed:
  - target_return      → (next_open → next_close) % change
  - target_direction   → 1 if target_return > 0 else 0 (binary classifier target)
  - target_high_pct    → (next_high - next_open) / next_open (range regressor target)
  - target_low_pct     → (next_low - next_open) / next_open
  - target_abs_return  → abs(target_return) (for magnitude/volatility modeling)
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from ..common.logger import get_logger
from ..db.models import MarketDataDaily
from ..db.session import get_session

logger = get_logger(__name__)

TARGET_COLS: list[str] = [
    "target_return",
    "target_direction",
    "target_high_pct",
    "target_low_pct",
    "target_abs_return",
]


def _fetch_ohlcv_for_stocks(
    stock_ids: list[int], start: date, end: date
) -> pd.DataFrame:
    """Bulk-load OHLCV for many stocks in one query. Returns long DataFrame."""
    with get_session() as s:
        rows = s.execute(
            select(
                MarketDataDaily.stock_id,
                MarketDataDaily.trade_date,
                MarketDataDaily.open,
                MarketDataDaily.high,
                MarketDataDaily.low,
                MarketDataDaily.close,
            )
            .where(
                MarketDataDaily.stock_id.in_(stock_ids),
                MarketDataDaily.trade_date >= start,
                MarketDataDaily.trade_date <= end,
            )
            .order_by(MarketDataDaily.stock_id, MarketDataDaily.trade_date)
        ).all()

    df = pd.DataFrame(rows, columns=["stock_id", "trade_date", "open", "high", "low", "close"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def add_labels(
    features_df: pd.DataFrame, horizon_days: int = 1, future_buffer_days: int = 30
) -> pd.DataFrame:
    """Attach next-trading-day OHLCV-derived labels to the feature matrix.

    Rows where the next-day OHLCV isn't available (e.g., the most recent date)
    will have NaN labels — those rows should be filtered out before training.
    """
    if features_df.empty:
        return features_df.copy()

    stock_ids = features_df["stock_id"].unique().tolist()
    min_date = pd.to_datetime(features_df["trade_date"]).min().date()
    max_date = pd.to_datetime(features_df["trade_date"]).max().date() + timedelta(
        days=future_buffer_days
    )

    # Fetch OHLCV window
    ohlcv = _fetch_ohlcv_for_stocks(stock_ids, min_date, max_date)
    if ohlcv.empty:
        logger.warning("no_ohlcv_for_labels")
        for col in TARGET_COLS:
            features_df[col] = pd.NA
        return features_df

    # For each (stock, date), compute next-trading-day OHLCV via groupby+shift
    ohlcv = ohlcv.sort_values(["stock_id", "trade_date"]).reset_index(drop=True)
    shift_n = -horizon_days
    g = ohlcv.groupby("stock_id", group_keys=False)
    ohlcv["next_open"] = g["open"].shift(shift_n)
    ohlcv["next_high"] = g["high"].shift(shift_n)
    ohlcv["next_low"] = g["low"].shift(shift_n)
    ohlcv["next_close"] = g["close"].shift(shift_n)

    next_open = ohlcv["next_open"]
    ohlcv["target_return"] = (ohlcv["next_close"] - next_open) / next_open
    ohlcv["target_direction"] = (ohlcv["target_return"] > 0).astype("Int64")
    ohlcv["target_high_pct"] = (ohlcv["next_high"] - next_open) / next_open
    ohlcv["target_low_pct"] = (ohlcv["next_low"] - next_open) / next_open
    ohlcv["target_abs_return"] = ohlcv["target_return"].abs()

    label_cols = ["stock_id", "trade_date"] + TARGET_COLS
    labels = ohlcv[label_cols]

    # Merge onto features
    features_df = features_df.copy()
    features_df["trade_date"] = pd.to_datetime(features_df["trade_date"])
    merged = features_df.merge(labels, on=["stock_id", "trade_date"], how="left")

    logger.info(
        "labels_attached",
        rows=len(merged),
        with_labels=int(merged["target_direction"].notna().sum()),
        null_labels=int(merged["target_direction"].isna().sum()),
    )
    return merged
