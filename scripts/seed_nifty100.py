"""Expand the stock universe from Nifty 50 to Nifty 100.

Nifty 100 = Nifty 50 + Nifty Next 50. We fetch NSE's official CSV, upsert
~50 new stocks into the stocks table, and insert NIFTY100 membership rows
in stock_universe_history. Existing NIFTY50 rows are kept untouched.

Usage:
    python scripts/seed_nifty100.py
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

from src.common.config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from src.common.logger import setup_logging
from src.common.sector_taxonomy import industry_to_sector
from src.db.models import Stock, StockUniverseHistory
from src.db.session import get_session

setup_logging()
console = Console()

NSE_NIFTY100_URL = "https://archives.nseindia.com/content/indices/ind_nifty100list.csv"


def fetch_nifty100() -> list[tuple]:
    """Return list of (symbol, name, yf_ticker, isin, industry) tuples from NSE."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/csv,*/*",
    }
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        resp = client.get(NSE_NIFTY100_URL)
        resp.raise_for_status()
        content = resp.text

    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for r in reader:
        symbol = (r.get("Symbol") or "").strip()
        name = (r.get("Company Name") or "").strip()
        isin = (r.get("ISIN Code") or "").strip() or None
        industry = (r.get("Industry") or "").strip() or None
        if not symbol:
            continue
        rows.append((symbol, name, f"{symbol}.NS", isin, industry))
    return rows


def seed_stocks(stocks_list: list[tuple]) -> dict[str, int]:
    """Upsert stocks (new rows inserted, existing updated). Returns symbol → id map."""
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4",
    )
    today = date.today()
    sql = """
        INSERT INTO stocks
            (symbol, name, nse_symbol, isin, yfinance_ticker, sector, industry,
             currently_active, first_seen_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s)
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            isin = VALUES(isin),
            sector = VALUES(sector),
            industry = VALUES(industry),
            currently_active = TRUE,
            updated_at = CURRENT_TIMESTAMP
    """
    try:
        with conn.cursor() as cur:
            for symbol, name, yf_ticker, isin, industry in stocks_list:
                canonical_sector = industry_to_sector(industry)
                cur.execute(sql, (
                    symbol, name, symbol, isin, yf_ticker,
                    canonical_sector, industry, today,
                ))
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT id, symbol FROM stocks")
            return {r[1]: r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def seed_universe_rows(symbol_to_id: dict[str, int], current_symbols: list[str]) -> int:
    """Add NIFTY100 membership rows for every current member."""
    seed_from = date(2020, 1, 1)  # backdated for practical V1 backtests
    sql = """
        INSERT IGNORE INTO stock_universe_history
            (universe_name, stock_id, valid_from, valid_to, rebalance_event, change_reason)
        VALUES ('NIFTY100', %s, %s, NULL, 'INITIAL', 'seeded from NSE Nifty 100 list')
    """
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4",
    )
    inserted = 0
    try:
        with conn.cursor() as cur:
            for symbol in current_symbols:
                stock_id = symbol_to_id.get(symbol)
                if not stock_id:
                    continue
                cur.execute(sql, (stock_id, seed_from))
                inserted += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return inserted


def print_summary():
    """Show final state — stocks, universe memberships, sector distribution."""
    with get_session() as s:
        total_stocks = s.scalar(select(func.count(Stock.id))) or 0
        nifty50 = s.scalar(
            select(func.count(StockUniverseHistory.id))
            .where(StockUniverseHistory.universe_name == "NIFTY50")
            .where(StockUniverseHistory.valid_to.is_(None))
        ) or 0
        nifty100 = s.scalar(
            select(func.count(StockUniverseHistory.id))
            .where(StockUniverseHistory.universe_name == "NIFTY100")
            .where(StockUniverseHistory.valid_to.is_(None))
        ) or 0
        sector_rows = s.execute(
            select(Stock.sector, func.count(Stock.id))
            .where(Stock.currently_active.is_(True))
            .group_by(Stock.sector)
            .order_by(func.count(Stock.id).desc())
        ).all()

    t = Table(title="Universe snapshot")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="green")
    t.add_row("Total stocks in catalog", str(total_stocks))
    t.add_row("Active NIFTY50 members", str(nifty50))
    t.add_row("Active NIFTY100 members", str(nifty100))
    console.print(t)

    st = Table(title="Canonical sector distribution (NIFTY100 universe)")
    st.add_column("Sector", style="magenta")
    st.add_column("Count", style="green")
    for sector, count in sector_rows:
        st.add_row(sector or "(unknown)", str(count))
    console.print(st)


def main() -> int:
    console.print("[cyan]▶ Expanding universe: Nifty 50 → Nifty 100[/cyan]\n")

    console.print("Fetching Nifty 100 from NSE...")
    stocks_list = fetch_nifty100()
    console.print(f"[green]✓ Fetched {len(stocks_list)} stocks[/green]")

    console.print("\nUpserting stocks (existing Nifty 50 updated, Next 50 added)...")
    symbol_to_id = seed_stocks(stocks_list)
    console.print(f"[green]✓ {len(symbol_to_id)} stocks in catalog[/green]")

    console.print("\nPopulating NIFTY100 membership...")
    current_symbols = [s[0] for s in stocks_list]
    inserted = seed_universe_rows(symbol_to_id, current_symbols)
    console.print(f"[green]✓ {inserted} new NIFTY100 rows[/green]")

    console.print()
    print_summary()
    console.print("\n[bold green]✓ Universe expansion complete[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
