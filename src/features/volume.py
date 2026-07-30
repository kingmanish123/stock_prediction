"""Volume features — volume ratios, turnover."""
from __future__ import annotations

import pandas as pd


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add volume-based features.

    volume_ratio_20d: today's volume / 20-day average (>1 = unusual activity)
    turnover_cr: traded value in crores (if not already present, compute from close × volume)
    """
    out = df.copy()
    volume = out["volume"]

    # Volume ratio (unusual activity detector)
    vol_avg_20d = volume.rolling(20).mean()
    out["volume_ratio_20d"] = volume / vol_avg_20d.replace(0, pd.NA)

    # Volume z-score (how many std devs from recent mean)
    vol_mean_20d = volume.rolling(20).mean()
    vol_std_20d = volume.rolling(20).std()
    out["volume_zscore_20d"] = (volume - vol_mean_20d) / vol_std_20d.replace(0, pd.NA)

    # Turnover (if not already in the df) — close * volume, in crores
    if "turnover_cr" not in out.columns or out["turnover_cr"].isna().all():
        out["turnover_cr"] = (out["close"] * volume) / 1e7  # ₹ crores
    out["turnover_ratio_20d"] = out["turnover_cr"] / out["turnover_cr"].rolling(20).mean().replace(0, pd.NA)

    return out


VOLUME_FEATURE_COLS: list[str] = [
    "volume_ratio_20d",
    "volume_zscore_20d",
    "turnover_ratio_20d",
]
