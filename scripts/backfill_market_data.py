"""Backfill historical OHLCV data for all Nifty 50 stocks.

Usage:
    python scripts/backfill_market_data.py                 # default: 5 years
    python scripts/backfill_market_data.py --years 3
    python scripts/backfill_market_data.py --days 30

This script logs a `runs` entry (run_type=backfill) so the operation is auditable.
Re-runnable safely — uses ON DUPLICATE KEY UPDATE to refresh existing rows.
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from sqlalchemy import func, select

from src.common.logger import setup_logging
from src.db.models import MarketDataDaily, Run, RunStatus, RunType, Stock
from src.db.session import get_session
from src.ingestion.market.yfinance_client import fetch_and_store_for_stock

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill OHLCV for Nifty 50 stocks")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--years", type=int, help="Number of years to backfill (default: 5)")
    g.add_argument("--days", type=int, help="Number of days to backfill")
    p.add_argument("--sleep-sec", type=float, default=0.3, help="Delay between ticker fetches")
    return p.parse_args()


def create_run(run_date: date, metadata: dict) -> int:
    """Create a runs row; return its id."""
    with get_session() as session:
        run = Run(
            run_type=RunType.BACKFILL,
            run_date=run_date,
            started_at=datetime.utcnow(),
            status=RunStatus.RUNNING,
            metadata_json=metadata,
        )
        session.add(run)
        session.flush()
        return run.id


def finalize_run(run_id: int, status: RunStatus, stats: dict) -> None:
    """Update the runs row with final stats."""
    with get_session() as session:
        run = session.get(Run, run_id)
        if not run:
            return
        run.status = status
        run.completed_at = datetime.utcnow()
        duration = (run.completed_at - run.started_at).total_seconds()
        run.duration_sec = int(duration)
        run.stocks_processed = stats.get("stocks_processed", 0)
        run.metadata_json = {**(run.metadata_json or {}), **stats}


def main() -> int:
    args = parse_args()

    if args.days:
        start = date.today() - timedelta(days=args.days)
        label = f"{args.days} days"
    else:
        years = args.years if args.years else 5
        start = date.today() - timedelta(days=years * 365)
        label = f"{years} years"
    end = date.today()

    console.print(f"[cyan]▶ Backfill Market Data — {label} ({start} to {end})[/cyan]\n")

    # Fetch active stocks
    with get_session() as session:
        stocks = session.scalars(
            select(Stock).where(Stock.currently_active.is_(True)).order_by(Stock.symbol)
        ).all()
        for s in stocks:
            session.expunge(s)

    console.print(f"  Targets: {len(stocks)} active Nifty 50 stocks")
    console.print(f"  Estimated API calls: {len(stocks)} (~{len(stocks) * args.sleep_sec:.0f}s min)\n")

    # Open run record
    run_id = create_run(
        end, {"start": start.isoformat(), "end": end.isoformat(), "period": label}
    )
    console.print(f"  Run ID: {run_id} (logged in runs table)\n")

    # Run with progress bar
    total_fetched = 0
    total_upserted = 0
    failures: list[str] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Fetching {len(stocks)} tickers", total=len(stocks))

        for stock in stocks:
            progress.update(task, description=f"[cyan]{stock.symbol}[/cyan]")
            result = fetch_and_store_for_stock(stock, start, end, sleep_sec=args.sleep_sec)
            if result.ok:
                total_fetched += result.rows_fetched
                total_upserted += result.rows_upserted
            else:
                failures.append(f"{stock.symbol}: {result.error}")
            progress.advance(task)

    # Finalize run
    final_status = RunStatus.SUCCESS if not failures else RunStatus.PARTIAL
    finalize_run(
        run_id,
        final_status,
        {
            "stocks_processed": len(stocks) - len(failures),
            "total_fetched": total_fetched,
            "total_upserted": total_upserted,
            "failures": failures,
        },
    )

    # Summary
    summary = Table(title="Backfill complete")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Stocks targeted", str(len(stocks)))
    summary.add_row("Successful", str(len(stocks) - len(failures)))
    summary.add_row("Failures", str(len(failures)))
    summary.add_row("Rows fetched (total)", f"{total_fetched:,}")
    summary.add_row("Rows upserted (DB-affected)", f"{total_upserted:,}")
    summary.add_row("Run ID", str(run_id))
    console.print(summary)

    if failures:
        console.print("\n[red]Failures:[/red]")
        for f in failures:
            console.print(f"  - {f}")

    # Verify final DB state
    with get_session() as session:
        total_rows = session.scalar(select(func.count(MarketDataDaily.id))) or 0
        unique_stocks = session.scalar(
            select(func.count(func.distinct(MarketDataDaily.stock_id)))
        ) or 0
        earliest = session.scalar(select(func.min(MarketDataDaily.trade_date)))
        latest = session.scalar(select(func.max(MarketDataDaily.trade_date)))

    coverage = Table(title="market_data_daily coverage")
    coverage.add_column("Metric", style="cyan")
    coverage.add_column("Value", style="green")
    coverage.add_row("Total rows in DB", f"{total_rows:,}")
    coverage.add_row("Distinct stocks", str(unique_stocks))
    coverage.add_row("Earliest date", str(earliest))
    coverage.add_row("Latest date", str(latest))
    console.print(coverage)

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
