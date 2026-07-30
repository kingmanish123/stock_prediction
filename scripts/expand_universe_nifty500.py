"""Expand universe from Nifty 100 → Nifty 500.

Nifty 500 covers ~95% of NSE's free-float market cap — large caps + midcaps +
small caps. This brings the prediction universe from 100 to ~500 stocks, which
is what the user wants ("any stock, not just Nifty 100").

Flow:
  1. Download NSE's official ind_nifty500list.csv
  2. Upsert all 500 into `stocks` table (new rows added, existing updated)
  3. Add NIFTY500 rows in stock_universe_history (valid_from = 2020-01-01 so
     backtests work)
  4. Re-run Upstox instrument mapping so new stocks get upstox_instrument_key

Follow-up (separate script):
    python scripts/backfill_market_data.py --years 1   # fetch OHLCV for new stocks

Usage:
    python scripts/expand_universe_nifty500.py
"""
import csv
import io
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pymysql
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from src.broker.instrument_map import seed_upstox_mapping
from src.common.config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from src.common.logger import setup_logging
from src.common.sector_taxonomy import industry_to_sector
from src.db.models import Stock, StockUniverseHistory
from src.db.session import get_session

setup_logging()
console = Console()

NSE_NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
UNIVERSE_NAME = "NIFTY500"
SEED_VALID_FROM = date(2020, 1, 1)  # backdated so past backtests work


def fetch_nifty500() -> list[tuple[str, str, str, str | None, str | None]]:
    """Return list of (symbol, name, yfinance_ticker, isin, industry) from NSE."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/csv,*/*",
    }
    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        resp = client.get(NSE_NIFTY500_URL)
        resp.raise_for_status()
        content = resp.text

    reader = csv.DictReader(io.StringIO(content))
    out: list[tuple] = []
    for r in reader:
        symbol = (r.get("Symbol") or "").strip()
        name = (r.get("Company Name") or "").strip()
        isin = (r.get("ISIN Code") or "").strip() or None
        industry = (r.get("Industry") or "").strip() or None
        if not symbol:
            continue
        out.append((symbol, name, f"{symbol}.NS", isin, industry))
    return out


def upsert_stocks(stocks_list: list[tuple]) -> tuple[dict[str, int], int, int]:
    """Upsert — returns (symbol→id map, newly_inserted_count, updated_count)."""
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4",
    )
    today = date.today()
    # Count existing before insert to distinguish new vs updated
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM stocks")
            pre_existing = {r[0] for r in cur.fetchall()}

        sql = """
            INSERT INTO stocks
                (symbol, name, nse_symbol, isin, yfinance_ticker, sector, industry,
                 currently_active, first_seen_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                isin = COALESCE(VALUES(isin), isin),
                sector = VALUES(sector),
                industry = VALUES(industry),
                currently_active = TRUE,
                updated_at = CURRENT_TIMESTAMP
        """
        new_count = 0
        upd_count = 0
        with conn.cursor() as cur:
            for symbol, name, yf_ticker, isin, industry in stocks_list:
                canonical_sector = industry_to_sector(industry)
                cur.execute(sql, (
                    symbol, name, symbol, isin, yf_ticker,
                    canonical_sector, industry, today,
                ))
                if symbol in pre_existing:
                    upd_count += 1
                else:
                    new_count += 1
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT id, symbol FROM stocks")
            sym_map = {r[1]: r[0] for r in cur.fetchall()}
        return sym_map, new_count, upd_count
    finally:
        conn.close()


def seed_universe_rows(symbol_to_id: dict[str, int], symbols: list[str]) -> int:
    """Add NIFTY500 rows to stock_universe_history (insert-ignore on dup)."""
    sql = """
        INSERT IGNORE INTO stock_universe_history
            (universe_name, stock_id, valid_from, valid_to, rebalance_event, change_reason)
        VALUES (%s, %s, %s, NULL, 'INITIAL', 'seeded from NSE Nifty 500 list')
    """
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4",
    )
    inserted = 0
    try:
        with conn.cursor() as cur:
            for symbol in symbols:
                stock_id = symbol_to_id.get(symbol)
                if not stock_id:
                    continue
                cur.execute(sql, (UNIVERSE_NAME, stock_id, SEED_VALID_FROM))
                inserted += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return inserted


def print_summary() -> None:
    with get_session() as s:
        total = s.scalar(select(func.count(Stock.id))) or 0
        active = s.scalar(
            select(func.count(Stock.id)).where(Stock.currently_active.is_(True))
        ) or 0
        n50 = s.scalar(
            select(func.count(StockUniverseHistory.id))
            .where(StockUniverseHistory.universe_name == "NIFTY50")
            .where(StockUniverseHistory.valid_to.is_(None))
        ) or 0
        n100 = s.scalar(
            select(func.count(StockUniverseHistory.id))
            .where(StockUniverseHistory.universe_name == "NIFTY100")
            .where(StockUniverseHistory.valid_to.is_(None))
        ) or 0
        n500 = s.scalar(
            select(func.count(StockUniverseHistory.id))
            .where(StockUniverseHistory.universe_name == "NIFTY500")
            .where(StockUniverseHistory.valid_to.is_(None))
        ) or 0

    t = Table(title="Universe snapshot")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="green")
    t.add_row("Total stocks in catalog", str(total))
    t.add_row("Currently active", str(active))
    t.add_row("NIFTY50 members", str(n50))
    t.add_row("NIFTY100 members", str(n100))
    t.add_row("NIFTY500 members", str(n500))
    console.print(t)


def main() -> int:
    console.print("[cyan]▶ Expanding universe: Nifty 100 → Nifty 500[/cyan]\n")

    console.print("[dim]Fetching NSE Nifty 500 list…[/dim]")
    try:
        stocks_list = fetch_nifty500()
    except Exception as e:
        console.print(f"[red]NSE fetch failed: {e}[/red]")
        return 1
    console.print(f"[green]✓ Fetched {len(stocks_list)} stocks[/green]")

    console.print("\n[dim]Upserting into stocks table…[/dim]")
    sym_map, new_count, upd_count = upsert_stocks(stocks_list)
    console.print(f"[green]✓ {new_count} newly inserted, {upd_count} updated[/green]")

    console.print("\n[dim]Populating NIFTY500 membership…[/dim]")
    symbols = [s[0] for s in stocks_list]
    inserted = seed_universe_rows(sym_map, symbols)
    console.print(f"[green]✓ {inserted} new NIFTY500 universe rows[/green]")

    console.print("\n[dim]Re-running Upstox instrument mapping…[/dim]")
    try:
        matched, total = seed_upstox_mapping()
        console.print(f"[green]✓ Mapped {matched}/{total} stocks to Upstox[/green]")
    except Exception as e:
        console.print(f"[yellow]Upstox mapping failed: {e} (not fatal)[/yellow]")

    console.print()
    print_summary()

    console.print("\n[bold cyan]Next step:[/bold cyan]")
    console.print("  1. Update .env: [yellow]UNIVERSE=NIFTY500[/yellow]")
    console.print(
        "  2. Backfill market data for new stocks: "
        "[yellow]python scripts/backfill_market_data.py --years 1[/yellow]"
    )
    console.print("\n[bold green]✓ Universe expansion complete[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
