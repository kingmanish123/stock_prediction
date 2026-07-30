"""Fetch OHLCV data for Indian stocks via yfinance and persist to MySQL.

yfinance is our primary market data source — free, reliable, handles `.NS` suffix
for NSE-listed stocks natively. Individual stock calls fetch the full history range
in a single request.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from ...common.logger import get_logger
from ...db.models import MarketDataDaily, Stock
from ...db.session import get_session
from .utils import safe_decimal as _safe_decimal
from .utils import safe_int as _safe_int

logger = get_logger(__name__)


@dataclass
class FetchResult:
    ticker: str
    rows_fetched: int
    rows_upserted: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# ─── fetch ───────────────────────────────────────────────────────────


def fetch_ohlcv(
    yf_ticker: str,
    start: date,
    end: date,
    retries: int = 3,
    backoff_sec: float = 2.0,
) -> pd.DataFrame | None:
    """Fetch daily OHLCV between start and end dates (inclusive).

    Returns a DataFrame with index=Date, columns=Open/High/Low/Close/Adj Close/Volume.
    Returns None if all retries exhausted.
    """
    end_exclusive = end + timedelta(days=1)
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            ticker = yf.Ticker(yf_ticker)
            df = ticker.history(
                start=start.isoformat(),
                end=end_exclusive.isoformat(),
                auto_adjust=False,
                actions=False,
            )
            if df.empty:
                logger.warning("yfinance_empty", ticker=yf_ticker, attempt=attempt)
                if attempt < retries:
                    time.sleep(backoff_sec * attempt)
                    continue
                return None
            return df
        except Exception as e:
            last_err = e
            logger.warning(
                "yfinance_fetch_failed",
                ticker=yf_ticker,
                attempt=attempt,
                error=str(e),
            )
            if attempt < retries:
                time.sleep(backoff_sec * attempt)
    logger.error("yfinance_exhausted", ticker=yf_ticker, error=str(last_err))
    return None


# ─── store ───────────────────────────────────────────────────────────


def upsert_ohlcv(stock_id: int, df: pd.DataFrame, source: str = "yfinance") -> int:
    """Bulk upsert OHLCV rows. Returns number of rows affected."""
    if df is None or df.empty:
        return 0

    rows: list[dict] = []
    for idx, row in df.iterrows():
        trade_date = idx.date() if hasattr(idx, "date") else idx
        rows.append(
            {
                "stock_id": stock_id,
                "trade_date": trade_date,
                "open": _safe_decimal(row.get("Open")),
                "high": _safe_decimal(row.get("High")),
                "low": _safe_decimal(row.get("Low")),
                "close": _safe_decimal(row.get("Close")),
                "adjusted_close": _safe_decimal(
                    row.get("Adj Close", row.get("Close"))
                ),
                "volume": _safe_int(row.get("Volume")),
                "data_source": source,
            }
        )

    if not rows:
        return 0

    stmt = mysql_insert(MarketDataDaily).values(rows)
    stmt = stmt.on_duplicate_key_update(
        open=stmt.inserted.open,
        high=stmt.inserted.high,
        low=stmt.inserted.low,
        close=stmt.inserted.close,
        adjusted_close=stmt.inserted.adjusted_close,
        volume=stmt.inserted.volume,
        data_source=stmt.inserted.data_source,
    )

    with get_session() as session:
        result = session.execute(stmt)
        return result.rowcount


# ─── high-level ──────────────────────────────────────────────────────


def get_active_nifty50() -> list[Stock]:
    """Return all currently active Nifty 50 stocks (ORM objects)."""
    with get_session() as session:
        stocks = session.scalars(
            select(Stock)
            .where(Stock.currently_active.is_(True))
            .order_by(Stock.symbol)
        ).all()
        for s in stocks:
            session.expunge(s)
        return list(stocks)


def fetch_and_store_for_stock(
    stock: Stock,
    start: date,
    end: date,
    sleep_sec: float = 0.3,
) -> FetchResult:
    """Fetch + persist OHLCV for one stock."""
    df = fetch_ohlcv(stock.yfinance_ticker, start, end)
    time.sleep(sleep_sec)  # gentle rate limit
    if df is None:
        return FetchResult(
            ticker=stock.yfinance_ticker,
            rows_fetched=0,
            rows_upserted=0,
            error="fetch_failed",
        )
    upserted = upsert_ohlcv(stock.id, df)
    return FetchResult(
        ticker=stock.yfinance_ticker,
        rows_fetched=len(df),
        rows_upserted=upserted,
    )


def fetch_and_store_bulk(
    stocks: Iterable[Stock],
    start: date,
    end: date,
    sleep_sec: float = 0.3,
    progress_cb=None,
) -> list[FetchResult]:
    """Fetch + persist for a list of stocks. Optional progress callback per stock."""
    results: list[FetchResult] = []
    for stock in stocks:
        result = fetch_and_store_for_stock(stock, start, end, sleep_sec)
        results.append(result)
        if progress_cb:
            progress_cb(result)
    return results
