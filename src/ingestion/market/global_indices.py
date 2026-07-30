"""Fetch OHLCV for global market indices + commodities + FX via yfinance.

These serve as `market_context` features — pre-market Nifty often correlates
with overnight US + Asia close, crude oil moves, and USD/INR direction.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from sqlalchemy.dialects.mysql import insert as mysql_insert

from ...common.logger import get_logger
from ...db.models import GlobalIndexDaily
from ...db.session import get_session
from .utils import safe_decimal, safe_int
from .yfinance_client import fetch_ohlcv

logger = get_logger(__name__)


@dataclass
class IndexSpec:
    symbol: str
    name: str
    country: str
    currency: str = "USD"


# Core indices + commodities + FX relevant to Indian markets
GLOBAL_INDICES: list[IndexSpec] = [
    # US (most important — overnight move = pre-market indicator)
    IndexSpec("^GSPC", "S&P 500", "US", "USD"),
    IndexSpec("^IXIC", "Nasdaq Composite", "US", "USD"),
    IndexSpec("^DJI", "Dow Jones Industrial", "US", "USD"),
    IndexSpec("^RUT", "Russell 2000", "US", "USD"),

    # Asia (opens before India, signals risk-on/off)
    IndexSpec("^N225", "Nikkei 225", "Japan", "JPY"),
    IndexSpec("^HSI", "Hang Seng", "Hong Kong", "HKD"),
    IndexSpec("000001.SS", "Shanghai Composite", "China", "CNY"),
    IndexSpec("^KS11", "KOSPI", "South Korea", "KRW"),

    # Europe
    IndexSpec("^FTSE", "FTSE 100", "UK", "GBP"),
    IndexSpec("^GDAXI", "DAX", "Germany", "EUR"),
    IndexSpec("^FCHI", "CAC 40", "France", "EUR"),

    # India (benchmark + sub-indices)
    IndexSpec("^NSEI", "Nifty 50", "India", "INR"),
    IndexSpec("^NSEBANK", "Nifty Bank", "India", "INR"),
    IndexSpec("^BSESN", "BSE Sensex", "India", "INR"),
    IndexSpec("^INDIAVIX", "India VIX", "India", "INR"),

    # Commodities (crude affects IT/energy; gold = safe-haven)
    IndexSpec("BZ=F", "Brent Crude Futures", "Global", "USD"),
    IndexSpec("CL=F", "WTI Crude Futures", "US", "USD"),
    IndexSpec("GC=F", "Gold Futures", "US", "USD"),
    IndexSpec("SI=F", "Silver Futures", "US", "USD"),

    # FX (USD/INR critical for FII flows)
    IndexSpec("INR=X", "USD/INR", "India", "INR"),
    IndexSpec("DX-Y.NYB", "US Dollar Index (DXY)", "US", "USD"),
    IndexSpec("EURINR=X", "EUR/INR", "India", "INR"),
]


def fetch_and_store_index(
    spec: IndexSpec, start: date, end: date, sleep_sec: float = 0.3
) -> dict:
    df = fetch_ohlcv(spec.symbol, start, end)
    time.sleep(sleep_sec)
    if df is None or df.empty:
        return {"symbol": spec.symbol, "name": spec.name, "rows": 0, "error": "fetch_failed"}

    df = df.copy()
    df["Prev Close"] = df["Close"].shift(1)
    df["Daily Return Pct"] = (df["Close"] - df["Prev Close"]) / df["Prev Close"] * 100

    rows = []
    for idx, row in df.iterrows():
        trade_date = idx.date() if hasattr(idx, "date") else idx
        rows.append(
            {
                "index_symbol": spec.symbol,
                "index_name": spec.name,
                "country": spec.country,
                "currency": spec.currency,
                "trade_date": trade_date,
                "open": safe_decimal(row.get("Open")),
                "high": safe_decimal(row.get("High")),
                "low": safe_decimal(row.get("Low")),
                "close": safe_decimal(row.get("Close")),
                "volume": safe_int(row.get("Volume")),
                "daily_return_pct": safe_decimal(row.get("Daily Return Pct"), places=4),
            }
        )

    if not rows:
        return {"symbol": spec.symbol, "name": spec.name, "rows": 0}

    stmt = mysql_insert(GlobalIndexDaily).values(rows)
    stmt = stmt.on_duplicate_key_update(
        index_name=stmt.inserted.index_name,
        open=stmt.inserted.open,
        high=stmt.inserted.high,
        low=stmt.inserted.low,
        close=stmt.inserted.close,
        volume=stmt.inserted.volume,
        daily_return_pct=stmt.inserted.daily_return_pct,
    )

    with get_session() as s:
        s.execute(stmt)

    return {"symbol": spec.symbol, "name": spec.name, "rows": len(rows)}


def backfill_all(
    start: date, end: date, sleep_sec: float = 0.3, specs: Iterable[IndexSpec] | None = None
) -> list[dict]:
    specs = list(specs) if specs is not None else GLOBAL_INDICES
    results = []
    for spec in specs:
        result = fetch_and_store_index(spec, start, end, sleep_sec)
        if result.get("error"):
            logger.warning(
                "global_index_failed", symbol=spec.symbol, error=result["error"]
            )
        else:
            logger.info("global_index_ok", symbol=spec.symbol, rows=result["rows"])
        results.append(result)
    return results
