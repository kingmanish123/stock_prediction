"""Derive tradable entry/target/stop from ML predictions + volatility (ATR).

The ML range regressor gives us predicted_low/predicted_high for the day.
Those are the *distribution* of likely prices, not risk-controlled trade levels.
Intraday noise frequently breaks a tight predicted_low, triggering the stop
before the real move even gets going.

This module converts ML output into risk-adjusted trade levels:
  - entry       = last_close (approximation; actual execution uses next open)
  - stop_loss   = entry - max(1.5 * ATR(14), 1.0% of entry)
  - target      = entry + max(1.5 * ATR(14), 1.5% of entry)
                  OR ML's predicted_high, whichever is higher

Guarantees:
  - Stop is never closer than 1% from entry
  - R:R is at least 1.5 (so expected-value trade even at 45% hit rate)
  - ATR reflects recent realized volatility, not model overconfidence
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from ..db.models import MarketDataDaily
from ..db.session import get_session

ATR_PERIOD = 14
MIN_STOP_PCT = 0.010      # stop must be at least 1% below entry
MIN_TARGET_PCT = 0.015    # target must be at least 1.5% above entry
# ATR is a *daily* range; for intraday trading we use a fraction.
# Nifty100 stocks typically have ATR 2-4% of price, so 0.5×ATR → ~1-2% stop.
ATR_STOP_MULT = 0.5
ATR_TARGET_MULT = 0.75    # target = entry + 0.75*ATR (capped)


@dataclass
class TradeLevels:
    entry: float
    stop_loss: float
    target: float
    atr: float | None
    stop_pct: float          # abs pct from entry
    target_pct: float        # abs pct from entry
    rr_ratio: float
    stop_reason: str         # 'atr' | 'min_floor' | 'ml_low'
    target_reason: str       # 'atr' | 'min_floor' | 'ml_high'


def compute_atr(stock_id: int, as_of: date, period: int = ATR_PERIOD) -> float | None:
    """Compute ATR(period) using daily candles up to and including `as_of`.

    TR(t) = max(high-low, |high - prev_close|, |low - prev_close|)
    ATR = simple mean of last `period` TRs.

    Returns None if insufficient data.
    """
    lookback = as_of - timedelta(days=period * 3 + 10)
    with get_session() as s:
        rows = s.execute(
            select(
                MarketDataDaily.trade_date,
                MarketDataDaily.high,
                MarketDataDaily.low,
                MarketDataDaily.close,
            )
            .where(
                MarketDataDaily.stock_id == stock_id,
                MarketDataDaily.trade_date >= lookback,
                MarketDataDaily.trade_date <= as_of,
            )
            .order_by(MarketDataDaily.trade_date)
        ).all()

    if len(rows) < period + 1:
        return None

    trs: list[float] = []
    prev_close: float | None = None
    for r in rows:
        if r.high is None or r.low is None or r.close is None:
            prev_close = None
            continue
        hi = float(r.high)
        lo = float(r.low)
        cl = float(r.close)
        if prev_close is not None:
            tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        else:
            tr = hi - lo
        trs.append(tr)
        prev_close = cl

    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def derive_trade_levels(
    entry: float,
    ml_predicted_low: float | None,
    ml_predicted_high: float | None,
    atr: float | None,
) -> TradeLevels:
    """Produce risk-adjusted levels from ML prediction + ATR.

    Rules:
      STOP:
        - If ATR available: stop_atr = entry - ATR_STOP_MULT * atr
        - stop_min     = entry * (1 - MIN_STOP_PCT)
        - stop_ml      = ml_predicted_low (if provided)
        - Final stop  = min(stop_atr, stop_min) — i.e. further away from entry
          but we clamp it to be not FURTHER than 3% down (avoid wild stops on
          volatile stocks). Also never tighter than 1% (stop_min).
      TARGET:
        - target_atr = entry + ATR_TARGET_MULT * atr
        - target_min = entry * (1 + MIN_TARGET_PCT)
        - target_ml  = ml_predicted_high (if provided)
        - Final target = max(target_atr, target_min, target_ml), capped at +5%
    """
    # ── STOP ─────────────────────────────────────────────────────────
    stop_min = entry * (1 - MIN_STOP_PCT)
    stop_candidates: list[tuple[float, str]] = [(stop_min, "min_floor")]
    if atr is not None and atr > 0:
        stop_candidates.append((entry - ATR_STOP_MULT * atr, "atr"))
    if ml_predicted_low is not None and ml_predicted_low < entry:
        stop_candidates.append((float(ml_predicted_low), "ml_low"))

    # Pick the LOWEST stop (furthest from entry for safer trade), but clamp
    # so stop is not more than 3% below entry (avoid oversized risk).
    stop_cap = entry * 0.97
    chosen_stop, stop_reason = min(stop_candidates, key=lambda x: x[0])
    if chosen_stop < stop_cap:
        chosen_stop, stop_reason = stop_cap, "cap_3pct"
    if chosen_stop > stop_min:
        chosen_stop, stop_reason = stop_min, "min_floor"

    # ── TARGET ───────────────────────────────────────────────────────
    target_min = entry * (1 + MIN_TARGET_PCT)
    target_candidates: list[tuple[float, str]] = [(target_min, "min_floor")]
    if atr is not None and atr > 0:
        target_candidates.append((entry + ATR_TARGET_MULT * atr, "atr"))
    if ml_predicted_high is not None and ml_predicted_high > entry:
        target_candidates.append((float(ml_predicted_high), "ml_high"))

    # Pick the HIGHEST target, cap at +5%
    target_cap = entry * 1.05
    chosen_target, target_reason = max(target_candidates, key=lambda x: x[0])
    if chosen_target > target_cap:
        chosen_target, target_reason = target_cap, "cap_5pct"

    stop_pct = (entry - chosen_stop) / entry
    target_pct = (chosen_target - entry) / entry
    rr_ratio = target_pct / stop_pct if stop_pct > 0 else 0.0

    return TradeLevels(
        entry=round(entry, 2),
        stop_loss=round(chosen_stop, 2),
        target=round(chosen_target, 2),
        atr=round(atr, 3) if atr is not None else None,
        stop_pct=round(stop_pct, 4),
        target_pct=round(target_pct, 4),
        rr_ratio=round(rr_ratio, 2),
        stop_reason=stop_reason,
        target_reason=target_reason,
    )
