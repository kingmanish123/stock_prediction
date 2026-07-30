"""Momentum features — multi-horizon returns + relative strength vs benchmark."""
from __future__ import annotations

import pandas as pd


def add_momentum_features(df: pd.DataFrame, benchmark_close: pd.Series | None = None) -> pd.DataFrame:
    """Add momentum feature columns.

    Returns are computed as percent changes over various windows. If benchmark_close
    is provided (e.g., Nifty 50 close), also computes relative strength.
    """
    out = df.copy()
    close = out["close"]

    # Returns over multiple horizons
    out["return_1d"] = close.pct_change(1)
    out["return_3d"] = close.pct_change(3)
    out["return_5d"] = close.pct_change(5)
    out["return_10d"] = close.pct_change(10)
    out["return_20d"] = close.pct_change(20)
    out["return_60d"] = close.pct_change(60)

    # Momentum score — weighted combination (AQR-style)
    # Recent short-term returns weighted higher
    out["momentum_score"] = (
        0.4 * out["return_5d"].fillna(0)
        + 0.3 * out["return_20d"].fillna(0)
        + 0.3 * out["return_60d"].fillna(0)
    )

    # Relative strength vs benchmark
    if benchmark_close is not None:
        # Align indices
        aligned_bench = benchmark_close.reindex(out.index).ffill()
        bench_return_5d = aligned_bench.pct_change(5)
        bench_return_20d = aligned_bench.pct_change(20)
        out["rel_strength_5d"] = out["return_5d"] - bench_return_5d
        out["rel_strength_20d"] = out["return_20d"] - bench_return_20d
    else:
        out["rel_strength_5d"] = pd.NA
        out["rel_strength_20d"] = pd.NA

    return out


MOMENTUM_FEATURE_COLS: list[str] = [
    "return_1d",
    "return_3d",
    "return_5d",
    "return_20d",
    "return_60d",
    "momentum_score",
    "rel_strength_5d",
    "rel_strength_20d",
]
