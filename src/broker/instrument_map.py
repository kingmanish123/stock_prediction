"""Map our `stocks.symbol` ↔ Upstox `instrument_key` via NSE ISIN matching.

Upstox publishes a master instruments CSV. We download it once, filter to
NSE equity, and update `stocks.upstox_instrument_key` by matching ISIN
(primary) or trading symbol (fallback).
"""
from __future__ import annotations

import gzip
import io

import httpx
import pandas as pd
from sqlalchemy import select

from ..common.logger import get_logger
from ..db.models import Stock
from ..db.session import get_session

logger = get_logger(__name__)

UPSTOX_INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
)


def download_instruments() -> pd.DataFrame:
    """Download + decompress Upstox's master instruments CSV."""
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(UPSTOX_INSTRUMENTS_URL)
        resp.raise_for_status()
    with gzip.open(io.BytesIO(resp.content), "rt") as f:
        df = pd.read_csv(f)
    return df


def seed_upstox_mapping() -> tuple[int, int]:
    """Match our stocks to Upstox instruments. Returns (matched, total)."""
    df = download_instruments()
    logger.info("upstox_instruments_downloaded", rows=len(df))

    # Filter to NSE equity segment. Column names may vary slightly across releases —
    # we detect the right columns defensively.
    seg_col = "segment" if "segment" in df.columns else "exchange"
    nse_mask = (df.get("exchange") == "NSE_EQ") | (df.get("exchange") == "NSE") | (df.get("segment") == "NSE_EQ")
    nse_eq = df[nse_mask].copy()

    # Normalize expected columns
    for col in ("instrument_key", "isin", "trading_symbol", "tradingsymbol"):
        if col in nse_eq.columns:
            nse_eq[col] = nse_eq[col].astype(str)

    # Different CSV versions call this field different names
    if "trading_symbol" in nse_eq.columns:
        ts_col = "trading_symbol"
    elif "tradingsymbol" in nse_eq.columns:
        ts_col = "tradingsymbol"
    else:
        ts_col = None

    isin_to_key = (
        nse_eq.set_index("isin")["instrument_key"].to_dict()
        if "isin" in nse_eq.columns and "instrument_key" in nse_eq.columns
        else {}
    )
    sym_to_key = (
        nse_eq.set_index(ts_col)["instrument_key"].to_dict()
        if ts_col and "instrument_key" in nse_eq.columns
        else {}
    )

    matched = 0
    total = 0
    unmatched_symbols: list[str] = []
    with get_session() as s:
        stocks = s.scalars(select(Stock)).all()
        for stock in stocks:
            total += 1
            key = None
            if stock.isin and stock.isin in isin_to_key:
                key = isin_to_key[stock.isin]
            elif stock.nse_symbol in sym_to_key:
                key = sym_to_key[stock.nse_symbol]
            if key:
                stock.upstox_instrument_key = key
                matched += 1
            else:
                unmatched_symbols.append(stock.symbol)

    if unmatched_symbols:
        logger.warning("upstox_unmatched_stocks", symbols=unmatched_symbols[:10])

    return matched, total


def get_symbol_to_instrument_map() -> dict[str, str]:
    """Return {symbol: upstox_instrument_key} for all mapped stocks."""
    with get_session() as s:
        rows = s.execute(
            select(Stock.symbol, Stock.upstox_instrument_key).where(
                Stock.upstox_instrument_key.isnot(None)
            )
        ).all()
    return {r.symbol: r.upstox_instrument_key for r in rows}
