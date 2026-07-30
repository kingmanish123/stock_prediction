"""XGBoost-based supplementary predictor.

When the news-driven pipeline doesn't produce enough high-conviction BUY
candidates, we fall back to our trained direction classifier (v3) to fill
the Top-10 list. This gives us a consistent 10-pick daily output even when
the news flow is dominated by bearish themes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import desc, select

from ..common.logger import get_logger
from ..db.models import MarketDataDaily, ModelVersion, Stock
from ..db.session import get_session
from ..features.assembler import build_feature_matrix
from .direction_classifier import DirectionClassifier

logger = get_logger(__name__)


@dataclass
class XGBoostPick:
    stock_id: int
    symbol: str
    name: str
    sector: str
    last_close: float | None
    prob_up: float


def _load_active_model() -> tuple[DirectionClassifier, ModelVersion] | None:
    with get_session() as s:
        mv = s.scalar(
            select(ModelVersion)
            .where(
                ModelVersion.model_name == "direction_classifier",
                ModelVersion.is_active.is_(True),
                ModelVersion.algorithm == "xgboost",
            )
            .order_by(desc(ModelVersion.trained_at))
        )
        if mv is None:
            return None
        s.expunge(mv)
    if not mv.file_path or not Path(mv.file_path).exists():
        logger.warning("xgb_model_file_missing", path=mv.file_path)
        return None
    return DirectionClassifier.load(mv.file_path), mv


_BEARISH_TITLE_KEYWORDS = (
    "profit fall", "profit decline", "net profit slips", "profit slips",
    "profit down", "profit drops", "profit plunge",
    "target cut", "target price falls", "downgrade", "downgraded",
    "weak q", "weak guidance", "weak results", "weak earnings",
    "miss estimate", "misses estimate", "earnings miss",
    "share price fall", "share price drop", "shares tumble", "stock falls",
    "wipes out", "drags", "decline in return", "revenue decline",
    "loss widens", "net loss",
)


def _title_based_bearish_veto(news: list[dict], min_matches: int = 2) -> tuple[bool, int]:
    """Fallback when sentiment labels are missing — scan titles for bearish keywords."""
    hits = 0
    for n in news:
        title = (n.get("title") or "").lower()
        if any(kw in title for kw in _BEARISH_TITLE_KEYWORDS):
            hits += 1
    return hits >= min_matches, hits


def _has_trap_flag(stock_id: int, feature_date: date) -> tuple[bool, str]:
    """Check rally+low-vol, bearish-news, and technical-overbought traps."""
    # Inline import to avoid circular dependency at module load
    from ..nlp.stock_reasoner import (
        _fetch_stock_news_snippets,
        _fetch_technical_snapshot,
        is_bearish_news_veto,
    )
    from .technical_indicators import compute_ta_snapshot

    tech = _fetch_technical_snapshot(stock_id, feature_date)
    r5 = tech.get("return_5d_pct") or 0
    r20 = tech.get("return_20d_pct") or 0
    vr = tech.get("volume_ratio_20d")
    # Rally + low institutional participation = classic bull trap
    if (r5 > 5 and (vr is None or vr < 0.7)):
        return True, f"rallied_5d+low_vol (r5={r5:.1f}% vr={vr})"
    if (r5 > 10 and (vr is None or vr < 1.0)):
        return True, f"rallied_5d_hard+weak_vol (r5={r5:.1f}% vr={vr})"
    if (r20 > 25 and (vr is None or vr < 1.0)):
        return True, f"rallied_20d+low_vol (r20={r20:.1f}% vr={vr})"

    # Technical chart veto — RSI overbought + MACD flip-down = high reversal risk
    ta = compute_ta_snapshot(stock_id, feature_date)
    if ta is not None:
        if ta.rsi_14 is not None and ta.rsi_14 > 75:
            return True, f"rsi_overbought (RSI={ta.rsi_14:.1f})"
        # Fresh bearish MACD cross (within last 2 days)
        xover = ta.macd_crossover_days
        if xover is not None and -2 <= xover < 0:
            return True, f"macd_just_flipped_bearish ({xover}d ago)"

    # Next-day news window for veto (pre-market + overnight)
    news = _fetch_stock_news_snippets(stock_id, feature_date + timedelta(days=1))
    # Primary: explicit sentiment-label veto
    if is_bearish_news_veto(news):
        neg = sum(1 for n in news if n.get("sentiment") == "negative")
        return True, f"bearish_news ({neg} negative articles)"
    # Fallback: title-keyword scan (when sentiment labeling didn't run)
    title_bearish, hits = _title_based_bearish_veto(news)
    if title_bearish:
        return True, f"bearish_title_keywords ({hits} hits)"

    return False, ""


def xgboost_top_buys(
    feature_date: date,
    exclude_stock_ids: Iterable[int] = (),
    n: int = 10,
    lookback_days: int = 7,
) -> list[XGBoostPick]:
    """Return top-n BUY candidates by XGBoost prob_up, excluding specified stocks
    and filtering out rally-trap + bearish-news picks."""

    loaded = _load_active_model()
    if loaded is None:
        logger.warning("xgb_no_active_model")
        return []
    clf, mv = loaded

    # Build features for feature_date
    features = build_feature_matrix(
        feature_date - timedelta(days=lookback_days),
        feature_date,
        write_parquet=False,
    )
    features["trade_date"] = pd.to_datetime(features["trade_date"])
    latest = features[features["trade_date"] == pd.Timestamp(feature_date)].copy()

    if latest.empty:
        logger.warning("xgb_no_features_for_date", date=str(feature_date))
        return []

    # Align to model's feature names
    missing = [c for c in clf.feature_names if c not in latest.columns]
    if missing:
        logger.warning("xgb_missing_features", missing=missing[:3])
        return []

    X = latest[clf.feature_names]
    complete = X.notna().all(axis=1)
    latest = latest[complete].copy()
    X = X[complete]
    if latest.empty:
        return []

    probs = clf.predict_proba(X)[:, 1]
    latest["prob_up"] = probs

    # Join last_close and metadata
    exclude_set = set(exclude_stock_ids)
    latest = latest[~latest["stock_id"].isin(exclude_set)].copy()

    # Pull last_close + Stock metadata
    with get_session() as s:
        close_rows = s.execute(
            select(MarketDataDaily.stock_id, MarketDataDaily.close).where(
                MarketDataDaily.trade_date == feature_date
            )
        ).all()
        close_map = {r.stock_id: float(r.close) for r in close_rows}

        stock_meta = s.execute(
            select(Stock.id, Stock.symbol, Stock.name, Stock.sector)
        ).all()
        meta_map = {r.id: {"symbol": r.symbol, "name": r.name, "sector": r.sector} for r in stock_meta}

    # TA-based tiebreaker score: XGBoost v3 gives many ties on the wider universe,
    # so we use technical indicators to rank stocks with similar prob_up.
    from .technical_indicators import compute_ta_snapshot

    def _ta_score(stock_id: int) -> float:
        """Score 0-1 where higher = better BUY setup based on chart indicators."""
        ta = compute_ta_snapshot(stock_id, feature_date)
        if ta is None:
            return 0.0
        score = 0.0
        # Momentum sweet spot (not overbought, not oversold)
        if ta.rsi_14 is not None and 40 <= ta.rsi_14 <= 60:
            score += 0.20
        # Fresh bullish MACD cross (last 7 days)
        if ta.macd_crossover_days is not None and 0 < ta.macd_crossover_days <= 7:
            score += 0.30
        elif ta.macd is not None and ta.macd_signal is not None and ta.macd > ta.macd_signal:
            score += 0.10
        # Golden cross (EMA20 > EMA50)
        if ta.ema_cross_state == "golden":
            score += 0.20
        # Oversold bounce setup (at lower band + RSI low)
        if ta.oversold and ta.bb_pct_b is not None and ta.bb_pct_b < 0.15:
            score += 0.20
        # Near support (within 2%) = better R:R
        if ta.near_support:
            score += 0.10
        # PENALTY: near resistance (likely to reject)
        if ta.near_resistance:
            score -= 0.15
        return max(0.0, min(1.0, score))

    # Get top N*5 candidates, compute TA score, then re-sort by (prob_up, ta_score)
    candidate_df = latest.nlargest(n * 5, "prob_up").copy()
    candidate_df["ta_score"] = candidate_df["stock_id"].apply(_ta_score)
    # Combined ranking: primary prob_up, tiebreak by ta_score
    candidate_df = candidate_df.sort_values(
        ["prob_up", "ta_score"], ascending=[False, False]
    )

    picks: list[XGBoostPick] = []
    skipped: list[tuple[str, str]] = []
    for _, row in candidate_df.iterrows():
        if len(picks) >= n:
            break
        sid = int(row["stock_id"])
        meta = meta_map.get(sid, {"symbol": "?", "name": "?", "sector": "?"})

        trapped, reason = _has_trap_flag(sid, feature_date)
        if trapped:
            skipped.append((meta["symbol"], reason))
            continue

        picks.append(XGBoostPick(
            stock_id=sid,
            symbol=meta["symbol"],
            name=meta["name"],
            sector=meta["sector"] or "other",
            last_close=close_map.get(sid),
            prob_up=float(row["prob_up"]),
        ))

    if skipped:
        logger.info("xgb_trap_skipped", count=len(skipped), examples=skipped[:5])

    return picks
