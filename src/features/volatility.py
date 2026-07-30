"""Volatility features — realized vol, regime classification."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_volatility_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add volatility feature columns.

    realized_vol_Nd: annualized standard deviation of daily returns over N days.
    vol_regime: 0 = low, 1 = normal, 2 = high (based on 252-day percentile).
    """
    out = df.copy()

    # Daily log returns (more stable for vol calculations)
    log_ret = np.log(out["close"] / out["close"].shift(1))

    # Realized annualized volatility over different windows
    # Factor 252 = trading days per year (annualization)
    sqrt252 = np.sqrt(252)
    out["realized_vol_5d"] = log_ret.rolling(5).std() * sqrt252
    out["realized_vol_20d"] = log_ret.rolling(20).std() * sqrt252
    out["realized_vol_60d"] = log_ret.rolling(60).std() * sqrt252

    # Vol regime — percentile of current 20d vol against trailing 252 days
    vol20 = out["realized_vol_20d"]
    vol20_pct = vol20.rolling(252).rank(pct=True)
    out["vol_regime"] = pd.cut(
        vol20_pct,
        bins=[-0.01, 0.33, 0.66, 1.01],
        labels=[0, 1, 2],
    ).astype(float)

    # Range expansion — today's high-low range vs 20-day avg
    hl_range = (out["high"] - out["low"]) / out["close"]
    hl_range_20d_avg = hl_range.rolling(20).mean()
    out["range_expansion"] = hl_range / hl_range_20d_avg.replace(0, pd.NA)

    return out


VOLATILITY_FEATURE_COLS: list[str] = [
    "realized_vol_5d",
    "realized_vol_20d",
    "realized_vol_60d",
    "vol_regime",
    "range_expansion",
]
