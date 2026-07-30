"""Technical indicators computed from daily candles.

Single entry point: `compute_ta_snapshot(stock_id, as_of)` returns a
`TASnapshot` with RSI, MACD, Bollinger, EMA crossover, support/resistance
proximity — everything needed to enrich the LLM prompt and pre-filter picks.

Design principles:
  - Read-only: computes from market_data_daily, no writes
  - Pure functions on numpy arrays where possible (easy to unit test)
  - Graceful: returns None fields for insufficient data rather than crashing
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select

from ..db.models import MarketDataDaily
from ..db.session import get_session

LOOKBACK_DAYS = 120  # calendar days — enough for 50+ trading days of indicators


@dataclass
class TASnapshot:
    """Lightweight bag of technical indicators as of a given date."""

    last_close: float
    # Momentum
    rsi_14: float | None
    # Trend
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    macd_crossover_days: int | None      # days since last bullish cross; -n for bearish
    ema_20: float | None
    ema_50: float | None
    ema_cross_state: str                  # "golden" | "death" | "none"
    # Volatility
    bb_upper: float | None
    bb_lower: float | None
    bb_pct_b: float | None                # 0.0 = at lower band, 1.0 = at upper band
    atr_14: float | None
    # Structure
    support_20d: float | None              # 20-day low
    resistance_20d: float | None           # 20-day high
    # Flags (derived)
    overbought: bool
    oversold: bool
    near_resistance: bool                  # within 2% of 20d high
    near_support: bool                     # within 2% of 20d low

    def summary(self) -> str:
        """Compact human-readable summary for LLM prompts (3-5 lines)."""
        lines: list[str] = []
        # Momentum line
        if self.rsi_14 is not None:
            rsi_desc = (
                "OVERBOUGHT" if self.overbought else
                "OVERSOLD" if self.oversold else
                "neutral"
            )
            lines.append(f"RSI(14)={self.rsi_14:.1f} [{rsi_desc}]")

        # Trend line
        if self.macd is not None and self.macd_signal is not None:
            trend = "bullish" if self.macd > self.macd_signal else "bearish"
            days = self.macd_crossover_days
            days_str = f"crossed {days}d ago" if days is not None else "no recent cross"
            lines.append(
                f"MACD={self.macd:.2f} vs signal={self.macd_signal:.2f} "
                f"[{trend}, {days_str}]"
            )

        # EMA trend
        if self.ema_20 is not None and self.ema_50 is not None:
            cross = self.ema_cross_state
            ema_diff_pct = (self.ema_20 - self.ema_50) / self.ema_50 * 100
            lines.append(
                f"EMA20={self.ema_20:.2f} EMA50={self.ema_50:.2f} "
                f"[{cross} cross, EMA20 {ema_diff_pct:+.1f}% vs EMA50]"
            )

        # Bollinger
        if self.bb_pct_b is not None:
            where = (
                "at upper band (distribution)" if self.bb_pct_b > 0.9 else
                "at lower band (accumulation)" if self.bb_pct_b < 0.1 else
                f"mid-band %b={self.bb_pct_b:.2f}"
            )
            lines.append(f"Bollinger: {where}")

        # Levels
        if self.support_20d and self.resistance_20d:
            where = ""
            if self.near_resistance:
                where = " — NEAR RESISTANCE"
            elif self.near_support:
                where = " — NEAR SUPPORT"
            lines.append(
                f"20d range: support ₹{self.support_20d:.2f} "
                f"/ resistance ₹{self.resistance_20d:.2f}{where}"
            )
        return "\n".join(lines) if lines else "(insufficient data)"


# ─── Pure math helpers ──────────────────────────────────────────────


def _rsi(closes: np.ndarray, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    # Wilder's smoothing (simple-mean seed, then EMA-like recursion)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Return full EMA series aligned to input length."""
    if len(values) == 0:
        return np.array([])
    alpha = 2 / (period + 1)
    out = np.zeros_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _macd(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | tuple[None, None, None]:
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _macd_crossover_days(macd_line: np.ndarray, signal_line: np.ndarray) -> int | None:
    """Days since last crossover. Positive = bullish (macd>signal), negative = bearish."""
    if macd_line is None or len(macd_line) < 2:
        return None
    diff = macd_line - signal_line
    # Find last sign change
    for i in range(len(diff) - 1, 0, -1):
        if (diff[i] > 0 and diff[i - 1] <= 0) or (diff[i] < 0 and diff[i - 1] >= 0):
            days_ago = len(diff) - 1 - i
            return days_ago if diff[-1] > 0 else -days_ago
    # No crossover found in window — return None (unknown)
    return None


def _bollinger(closes: np.ndarray, period: int = 20, stdev_mult: float = 2.0) -> tuple[float, float, float] | tuple[None, None, None]:
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mid = window.mean()
    std = window.std(ddof=0)
    upper = mid + stdev_mult * std
    lower = mid - stdev_mult * std
    last = closes[-1]
    pct_b = (last - lower) / (upper - lower) if upper > lower else 0.5
    return float(upper), float(lower), float(pct_b)


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return float(np.mean(trs[-period:]))


# ─── DB glue ────────────────────────────────────────────────────────


def _fetch_candles(stock_id: int, as_of: date, lookback_days: int = LOOKBACK_DAYS):
    cutoff = as_of - timedelta(days=lookback_days)
    with get_session() as s:
        rows = s.execute(
            select(
                MarketDataDaily.trade_date,
                MarketDataDaily.open,
                MarketDataDaily.high,
                MarketDataDaily.low,
                MarketDataDaily.close,
                MarketDataDaily.volume,
            )
            .where(
                MarketDataDaily.stock_id == stock_id,
                MarketDataDaily.trade_date >= cutoff,
                MarketDataDaily.trade_date <= as_of,
            )
            .order_by(MarketDataDaily.trade_date)
        ).all()
    return rows


def compute_ta_snapshot(stock_id: int, as_of: date) -> TASnapshot | None:
    """Primary entry point — returns TASnapshot with all indicators or None."""
    rows = _fetch_candles(stock_id, as_of)
    if len(rows) < 20:
        return None

    closes = np.array([float(r.close) for r in rows if r.close is not None])
    highs = np.array([float(r.high) for r in rows if r.high is not None])
    lows = np.array([float(r.low) for r in rows if r.low is not None])
    last_close = float(closes[-1])

    # RSI
    rsi = _rsi(closes, 14)

    # MACD
    macd_line, signal_line, hist = _macd(closes)
    macd_last = float(macd_line[-1]) if macd_line is not None else None
    signal_last = float(signal_line[-1]) if signal_line is not None else None
    hist_last = float(hist[-1]) if hist is not None else None
    xover_days = _macd_crossover_days(macd_line, signal_line) if macd_line is not None else None

    # EMA
    ema_20 = _ema(closes, 20)
    ema_50 = _ema(closes, 50) if len(closes) >= 50 else None
    ema_20_last = float(ema_20[-1]) if len(ema_20) else None
    ema_50_last = float(ema_50[-1]) if ema_50 is not None and len(ema_50) else None
    if ema_20_last is not None and ema_50_last is not None:
        ema_cross = "golden" if ema_20_last > ema_50_last else "death"
    else:
        ema_cross = "none"

    # Bollinger
    bb_upper, bb_lower, bb_pct_b = _bollinger(closes)

    # ATR
    atr = _atr(highs, lows, closes) if len(highs) == len(closes) and len(lows) == len(closes) else None

    # Support/Resistance — 20 trading day high/low
    window = min(20, len(closes))
    support_20d = float(lows[-window:].min()) if len(lows) >= window else None
    resistance_20d = float(highs[-window:].max()) if len(highs) >= window else None

    # Derived flags
    overbought = rsi is not None and rsi > 70
    oversold = rsi is not None and rsi < 30
    near_resistance = (
        resistance_20d is not None
        and last_close >= resistance_20d * 0.98
    )
    near_support = (
        support_20d is not None
        and last_close <= support_20d * 1.02
    )

    return TASnapshot(
        last_close=last_close,
        rsi_14=rsi,
        macd=macd_last,
        macd_signal=signal_last,
        macd_hist=hist_last,
        macd_crossover_days=xover_days,
        ema_20=ema_20_last,
        ema_50=ema_50_last,
        ema_cross_state=ema_cross,
        bb_upper=bb_upper,
        bb_lower=bb_lower,
        bb_pct_b=bb_pct_b,
        atr_14=atr,
        support_20d=support_20d,
        resistance_20d=resistance_20d,
        overbought=overbought,
        oversold=oversold,
        near_resistance=near_resistance,
        near_support=near_support,
    )
