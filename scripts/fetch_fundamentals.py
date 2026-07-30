"""Fetch stock fundamentals via yfinance and store in stock_fundamentals.

yfinance's `Ticker.info` dict gives us 60+ fields — we cherry-pick the ones
that actually drive analyst decisions: valuation (P/E, PEG), profitability
(margins, ROE), growth, debt, and 52-week range.

Schedule: weekly is plenty — fundamentals don't change intraday.

Usage:
    python scripts/fetch_fundamentals.py                # all currently_active stocks
    python scripts/fetch_fundamentals.py --symbols RELIANCE,INFY
"""
import argparse
import sys
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from src.common.logger import setup_logging
from src.db.models import Stock, StockFundamentals
from src.db.session import get_session

setup_logging()
console = Console()


def _dec(v, places: int = 4) -> Decimal | None:
    """Safely convert to Decimal, return None if not finite."""
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            if v != v or abs(v) == float("inf"):  # NaN or inf
                return None
            return Decimal(str(round(v, places)))
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def extract_fundamentals(ticker_info: dict, stock_id: int, snap_date: date) -> dict | None:
    """Map yfinance info dict → our stock_fundamentals row."""
    if not ticker_info or not isinstance(ticker_info, dict):
        return None

    # Market cap: yfinance gives INR for .NS tickers
    market_cap_raw = ticker_info.get("marketCap")
    market_cap_cr = _dec(market_cap_raw / 1e7, 2) if market_cap_raw else None

    total_cash = ticker_info.get("totalCash")
    total_debt = ticker_info.get("totalDebt")

    return {
        "stock_id": stock_id,
        "snapshot_date": snap_date,
        "pe_ratio": _dec(ticker_info.get("trailingPE"), 3),
        "forward_pe": _dec(ticker_info.get("forwardPE"), 3),
        "pb_ratio": _dec(ticker_info.get("priceToBook"), 3),
        "ps_ratio": _dec(ticker_info.get("priceToSalesTrailing12Months"), 3),
        "peg_ratio": _dec(ticker_info.get("trailingPegRatio") or ticker_info.get("pegRatio"), 3),
        "ev_to_ebitda": _dec(ticker_info.get("enterpriseToEbitda"), 3),
        "market_cap_cr": market_cap_cr,
        "shares_outstanding": _int(ticker_info.get("sharesOutstanding")),
        "float_shares": _int(ticker_info.get("floatShares")),
        "profit_margin": _dec(ticker_info.get("profitMargins"), 4),
        "operating_margin": _dec(ticker_info.get("operatingMargins"), 4),
        "roe": _dec(ticker_info.get("returnOnEquity"), 4),
        "roa": _dec(ticker_info.get("returnOnAssets"), 4),
        "revenue_growth_yoy": _dec(ticker_info.get("revenueGrowth"), 4),
        "earnings_growth_yoy": _dec(ticker_info.get("earningsGrowth"), 4),
        "quarterly_earnings_growth": _dec(ticker_info.get("earningsQuarterlyGrowth"), 4),
        "debt_to_equity": _dec(
            (ticker_info.get("debtToEquity") / 100) if ticker_info.get("debtToEquity") else None,
            3,
        ),
        "current_ratio": _dec(ticker_info.get("currentRatio"), 3),
        "total_cash_cr": _dec(total_cash / 1e7, 2) if total_cash else None,
        "total_debt_cr": _dec(total_debt / 1e7, 2) if total_debt else None,
        "dividend_yield": _dec(ticker_info.get("dividendYield"), 4),
        "payout_ratio": _dec(ticker_info.get("payoutRatio"), 4),
        "current_price": _dec(ticker_info.get("currentPrice") or ticker_info.get("regularMarketPrice"), 4),
        "fifty_two_week_high": _dec(ticker_info.get("fiftyTwoWeekHigh"), 4),
        "fifty_two_week_low": _dec(ticker_info.get("fiftyTwoWeekLow"), 4),
        "beta": _dec(ticker_info.get("beta"), 3),
        "data_source": "yfinance",
        "raw_json": {
            k: v for k, v in ticker_info.items()
            if isinstance(v, (str, int, float, bool)) and v is not None
        },
    }


def fetch_one(stock: Stock, snap_date: date, retries: int = 2) -> dict | None:
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(stock.yfinance_ticker)
            info = ticker.info
            return extract_fundamentals(info, stock.id, snap_date)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            console.print(f"  [red]✗ {stock.symbol}: {type(e).__name__}[/red]")
            return None
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", type=str, help="Comma-separated symbols (default: all active)")
    p.add_argument("--sleep-sec", type=float, default=0.25)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    snap_date = date.today()

    with get_session() as s:
        q = select(Stock).where(Stock.currently_active.is_(True)).order_by(Stock.symbol)
        if args.symbols:
            wanted = {x.strip().upper() for x in args.symbols.split(",")}
            q = q.where(Stock.symbol.in_(wanted))
        stocks = s.scalars(q).all()
        for x in stocks:
            s.expunge(x)

    console.print(f"[cyan]▶ Fetching fundamentals for {len(stocks)} stocks[/cyan]\n")

    rows: list[dict] = []
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching", total=len(stocks))
        for stock in stocks:
            progress.update(task, description=f"[cyan]{stock.symbol}[/cyan]")
            row = fetch_one(stock, snap_date)
            if row:
                rows.append(row)
            else:
                failed += 1
            time.sleep(args.sleep_sec)
            progress.advance(task)

    # Upsert in batches to avoid max_allowed_packet (raw_json is bulky)
    BATCH_SIZE = 25
    if rows:
        with get_session() as s:
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                stmt = mysql_insert(StockFundamentals).values(batch)
                update_cols = {
                    c: stmt.inserted[c]
                    for c in batch[0].keys()
                    if c not in ("stock_id", "snapshot_date")
                }
                stmt = stmt.on_duplicate_key_update(**update_cols)
                s.execute(stmt)
                s.commit()

    # Summary
    t = Table(title="Fundamentals fetch summary")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="green")
    t.add_row("Targets", str(len(stocks)))
    t.add_row("Persisted", str(len(rows)))
    t.add_row("Failed", str(failed))
    t.add_row("Snapshot date", str(snap_date))
    console.print(t)
    return 0 if failed < len(stocks) * 0.1 else 1


if __name__ == "__main__":
    sys.exit(main())
