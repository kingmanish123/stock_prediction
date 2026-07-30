"""Technical indicators — RSI, MACD, moving averages, Bollinger Bands, ATR.

Each function takes an OHLCV DataFrame (date-indexed) and returns a DataFrame
with feature columns added. Operates per-stock on the full time series so
lookback windows (e.g., RSI-14) resolve correctly.
"""
from __future__ import annotations

import ta
import pandas as pd


def add_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicator columns to OHLCV DataFrame.

    Expects columns: open, high, low, close, volume (case-insensitive).
    Returns DataFrame with original columns + new feature columns.
    """
    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]

    # RSI-14
    out["rsi_14"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

    # MACD (12, 26, 9) — histogram is the most predictive signal
    macd = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    out["macd_line"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["macd_hist"] = macd.macd_diff()

    # Simple moving averages + trend ratio
    sma20 = ta.trend.SMAIndicator(close=close, window=20).sma_indicator()
    sma50 = ta.trend.SMAIndicator(close=close, window=50).sma_indicator()
    out["sma_20"] = sma20
    out["sma_50"] = sma50
    out["sma_20_vs_50_ratio"] = (sma20 / sma50) - 1  # -1 = sma20 half of sma50

    # EMA (trend-following)
    out["ema_20"] = ta.trend.EMAIndicator(close=close, window=20).ema_indicator()
    out["close_vs_ema20_pct"] = (close / out["ema_20"]) - 1

    # Bollinger Bands position (0=lower band, 0.5=middle, 1=upper band)
    bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    out["bb_upper"] = bb.bollinger_hband()
    out["bb_lower"] = bb.bollinger_lband()
    band_width = bb.bollinger_hband() - bb.bollinger_lband()
    # Guard against division by zero (flat price series)
    out["bb_position"] = (close - bb.bollinger_lband()) / band_width.replace(0, pd.NA)
    out["bb_width_pct"] = band_width / bb.bollinger_mavg()  # squeeze indicator

    # ATR (Average True Range) as % of close — volatility
    atr = ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=14
    ).average_true_range()
    out["atr_14"] = atr
    out["atr_pct"] = atr / close  # normalized

    # Stochastic oscillator
    stoch = ta.momentum.StochasticOscillator(
        high=high, low=low, close=close, window=14, smooth_window=3
    )
    out["stoch_k"] = stoch.stoch()

    return out


TECHNICAL_FEATURE_COLS: list[str] = [
    "rsi_14",
    "macd_hist",
    "macd_signal",
    "sma_20_vs_50_ratio",
    "close_vs_ema20_pct",
    "bb_position",
    "bb_width_pct",
    "atr_pct",
    "stoch_k",
]
