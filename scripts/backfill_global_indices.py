"""Backfill global indices + commodities + FX data.

Usage:
    python scripts/backfill_global_indices.py                # default 5 years
    python scripts/backfill_global_indices.py --years 3
    python scripts/backfill_global_indices.py --days 30
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from sqlalchemy import func, select

from src.common.logger import setup_logging
from src.db.models import GlobalIndexDaily, Run, RunStatus, RunType
from src.db.session import get_session
from src.ingestion.market.global_indices import GLOBAL_INDICES, fetch_and_store_index

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--years", type=int)
    g.add_argument("--days", type=int)
    p.add_argument("--sleep-sec", type=float, default=0.3)
    return p.parse_args()


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

    console.print(f"[cyan]▶ Backfill Global Indices — {label}[/cyan]\n")
    console.print(f"  Targets: {len(GLOBAL_INDICES)} indices/commodities/FX")

    # log run
    with get_session() as s:
        run = Run(
            run_type=RunType.BACKFILL,
            run_date=end,
            started_at=datetime.utcnow(),
            status=RunStatus.RUNNING,
            metadata_json={"module": "global_indices", "period": label},
        )
        s.add(run)
        s.flush()
        run_id = run.id
    console.print(f"  Run ID: {run_id}\n")

    total_rows = 0
    failures = []

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
        task = progress.add_task("Fetching", total=len(GLOBAL_INDICES))
        for spec in GLOBAL_INDICES:
            progress.update(task, description=f"[cyan]{spec.symbol}[/cyan] — {spec.name}")
            result = fetch_and_store_index(spec, start, end, sleep_sec=args.sleep_sec)
            if result.get("error"):
                failures.append(f"{spec.symbol} ({spec.name}): {result['error']}")
            else:
                total_rows += result["rows"]
            progress.advance(task)

    # finalize run
    with get_session() as s:
        run = s.get(Run, run_id)
        run.status = RunStatus.SUCCESS if not failures else RunStatus.PARTIAL
        run.completed_at = datetime.utcnow()
        run.duration_sec = int((run.completed_at - run.started_at).total_seconds())
        run.stocks_processed = len(GLOBAL_INDICES) - len(failures)
        run.metadata_json = {
            **(run.metadata_json or {}),
            "total_rows": total_rows,
            "failures": failures,
        }

    summary = Table(title="Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Indices targeted", str(len(GLOBAL_INDICES)))
    summary.add_row("Successful", str(len(GLOBAL_INDICES) - len(failures)))
    summary.add_row("Failures", str(len(failures)))
    summary.add_row("Total rows inserted/updated", f"{total_rows:,}")
    console.print(summary)

    if failures:
        console.print("\n[yellow]Failures:[/yellow]")
        for f in failures:
            console.print(f"  • {f}")

    # Verify
    with get_session() as s:
        total = s.scalar(select(func.count(GlobalIndexDaily.id))) or 0
        distinct = s.scalar(select(func.count(func.distinct(GlobalIndexDaily.index_symbol)))) or 0
        latest_dates = s.execute(
            select(
                GlobalIndexDaily.index_symbol,
                GlobalIndexDaily.index_name,
                GlobalIndexDaily.close,
                GlobalIndexDaily.daily_return_pct,
                func.max(GlobalIndexDaily.trade_date).label("latest"),
            )
            .group_by(GlobalIndexDaily.index_symbol, GlobalIndexDaily.index_name,
                      GlobalIndexDaily.close, GlobalIndexDaily.daily_return_pct)
            .order_by(GlobalIndexDaily.index_symbol)
        ).all()

    coverage = Table(title="Current coverage in DB")
    coverage.add_column("Metric", style="cyan")
    coverage.add_column("Value", style="green")
    coverage.add_row("Total rows", f"{total:,}")
    coverage.add_row("Distinct indices", str(distinct))
    console.print(coverage)

    # Show latest close for each index
    latest_table = Table(title="Latest close by index")
    latest_table.add_column("Symbol", style="cyan")
    latest_table.add_column("Name")
    latest_table.add_column("Latest date")
    latest_table.add_column("Close", justify="right", style="green")
    latest_table.add_column("Δ%", justify="right")
    with get_session() as s:
        # get latest row per index (subquery approach)
        from sqlalchemy import and_
        subq = select(
            GlobalIndexDaily.index_symbol,
            func.max(GlobalIndexDaily.trade_date).label("max_date"),
        ).group_by(GlobalIndexDaily.index_symbol).subquery()
        rows = s.execute(
            select(
                GlobalIndexDaily.index_symbol,
                GlobalIndexDaily.index_name,
                GlobalIndexDaily.trade_date,
                GlobalIndexDaily.close,
                GlobalIndexDaily.daily_return_pct,
            ).join(
                subq,
                and_(
                    GlobalIndexDaily.index_symbol == subq.c.index_symbol,
                    GlobalIndexDaily.trade_date == subq.c.max_date,
                ),
            ).order_by(GlobalIndexDaily.index_symbol)
        ).all()
    for sym, name, tdate, close, ret in rows:
        ret_str = f"{ret:+.2f}%" if ret is not None else "-"
        color = "green" if (ret is not None and ret > 0) else ("red" if (ret is not None and ret < 0) else "")
        latest_table.add_row(
            sym, name, str(tdate), f"{close:.2f}" if close else "-",
            f"[{color}]{ret_str}[/{color}]" if color else ret_str,
        )
    console.print(latest_table)

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
