"""Market context features — global indices, macro indicators.

These features are shared across all stocks on any given date — they represent
the global/macro backdrop. Computed once per date and broadcast to every stock.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from ..db.models import GlobalIndexDaily, MacroDataDaily
from ..db.session import get_session


# Indices whose daily returns we include as features.
# These are the yfinance symbols stored in global_indices_daily.
MARKET_CONTEXT_INDICES: list[tuple[str, str]] = [
    ("^GSPC", "sp500"),
    ("^IXIC", "nasdaq"),
    ("^N225", "nikkei"),
    ("^HSI", "hang_seng"),
    ("^NSEI", "nifty50"),
    ("^NSEBANK", "nifty_bank"),
    ("^INDIAVIX", "india_vix"),
    ("BZ=F", "brent_crude"),
    ("GC=F", "gold"),
    ("INR=X", "usd_inr"),
    ("DX-Y.NYB", "dxy"),
]

# Macro indicators whose LEVEL (not change) we track.
MARKET_CONTEXT_MACROS: list[tuple[str, str]] = [
    ("VIXCLS", "us_vix"),
    ("DGS10", "us_10y_yield"),
    ("T10Y2Y", "yield_curve_spread"),
    ("FEDFUNDS", "fed_funds"),
    ("DCOILWTICO", "wti_crude_price"),
]


def load_market_context(start: date, end: date) -> pd.DataFrame:
    """Load global indices + macro data and compute per-date context features.

    Returns DataFrame indexed by date with columns like:
        sp500_1d_return, nasdaq_1d_return, ..., india_vix_level,
        us_vix, us_10y_yield, fed_funds, wti_crude_price.

    For any missing date (weekend/holiday), values are forward-filled from the
    last available session.
    """
    # Pull enough lookback for both short-term returns AND monthly macro series
    # (FRED monthly indicators like FEDFUNDS / CPI publish only once per month).
    fetch_start = start - timedelta(days=90)

    with get_session() as s:
        # Global indices
        rows = s.execute(
            select(
                GlobalIndexDaily.trade_date,
                GlobalIndexDaily.index_symbol,
                GlobalIndexDaily.close,
            ).where(
                GlobalIndexDaily.trade_date >= fetch_start,
                GlobalIndexDaily.trade_date <= end,
            )
        ).all()

        macro_rows = s.execute(
            select(
                MacroDataDaily.observation_date,
                MacroDataDaily.indicator_code,
                MacroDataDaily.value,
            ).where(
                MacroDataDaily.observation_date >= fetch_start,
                MacroDataDaily.observation_date <= end,
            )
        ).all()

    # Build indices wide DF
    idx_df = pd.DataFrame(rows, columns=["date", "symbol", "close"])
    idx_wide = idx_df.pivot(index="date", columns="symbol", values="close").sort_index()
    idx_wide.index = pd.to_datetime(idx_wide.index)

    # Macro wide DF
    macro_df = pd.DataFrame(macro_rows, columns=["date", "code", "value"])
    macro_wide = macro_df.pivot(index="date", columns="code", values="value").sort_index()
    macro_wide.index = pd.to_datetime(macro_wide.index)

    # Outer join, ffill across calendar
    full_idx = pd.date_range(start=fetch_start, end=end, freq="D")
    idx_wide = idx_wide.reindex(full_idx).ffill()
    macro_wide = macro_wide.reindex(full_idx).ffill()

    ctx = pd.DataFrame(index=full_idx)

    # Indices: daily + 5-day returns + levels for VIX
    for sym, name in MARKET_CONTEXT_INDICES:
        if sym in idx_wide.columns:
            series = idx_wide[sym].astype(float)
            ctx[f"{name}_1d_return"] = series.pct_change(1)
            ctx[f"{name}_5d_return"] = series.pct_change(5)
            # also keep absolute level for volatility-type indicators
            if name in {"india_vix"}:
                ctx[f"{name}_level"] = series

    # Macros: use level directly (these are already rates/percentages/indexes)
    for code, name in MARKET_CONTEXT_MACROS:
        if code in macro_wide.columns:
            ctx[name] = macro_wide[code].astype(float)

    # Cleanup: keep only dates >= requested start
    ctx = ctx.loc[ctx.index >= pd.Timestamp(start)]
    ctx.index.name = "date"
    return ctx


MARKET_CONTEXT_FEATURE_COLS: list[str] = (
    [f"{name}_1d_return" for _, name in MARKET_CONTEXT_INDICES]
    + [f"{name}_5d_return" for _, name in MARKET_CONTEXT_INDICES]
    + ["india_vix_level"]
    + [name for _, name in MARKET_CONTEXT_MACROS]
)
