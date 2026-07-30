"""Backfill FRED macro indicators.

Usage:
    python scripts/backfill_macro_data.py                # default 5 years
    python scripts/backfill_macro_data.py --years 10
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from sqlalchemy import and_, func, select

from src.common.logger import setup_logging
from src.db.models import MacroDataDaily, Run, RunStatus, RunType
from src.db.session import get_session
from src.ingestion.market.fred_client import MACRO_INDICATORS, fetch_and_store_indicator

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--years", type=int)
    g.add_argument("--days", type=int)
    p.add_argument("--sleep-sec", type=float, default=0.1)
    return p.parse_args()


def main() -> int:
    from fredapi import Fred
    from src.common.config import FRED_API_KEY

    if not FRED_API_KEY:
        console.print("[red]FRED_API_KEY not set in .env[/red]")
        return 1

    args = parse_args()
    if args.days:
        start = date.today() - timedelta(days=args.days)
        label = f"{args.days} days"
    else:
        years = args.years if args.years else 5
        start = date.today() - timedelta(days=years * 365)
        label = f"{years} years"
    end = date.today()

    console.print(f"[cyan]▶ Backfill FRED Macro Data — {label}[/cyan]\n")
    console.print(f"  Indicators: {len(MACRO_INDICATORS)}")

    with get_session() as s:
        run = Run(
            run_type=RunType.BACKFILL,
            run_date=end,
            started_at=datetime.utcnow(),
            status=RunStatus.RUNNING,
            metadata_json={"module": "fred_macro", "period": label},
        )
        s.add(run)
        s.flush()
        run_id = run.id
    console.print(f"  Run ID: {run_id}\n")

    fred = Fred(api_key=FRED_API_KEY)
    total_rows = 0
    failures = []

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), MofNCompleteColumn(),
        TextColumn("•"), TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Fetching", total=len(MACRO_INDICATORS))
        for spec in MACRO_INDICATORS:
            progress.update(task, description=f"[cyan]{spec.code}[/cyan] — {spec.name[:40]}")
            result = fetch_and_store_indicator(fred, spec, start, end, sleep_sec=args.sleep_sec)
            if result.get("error"):
                failures.append(f"{spec.code}: {result['error']}")
            else:
                total_rows += result["rows"]
            progress.advance(task)

    with get_session() as s:
        run = s.get(Run, run_id)
        run.status = RunStatus.SUCCESS if not failures else RunStatus.PARTIAL
        run.completed_at = datetime.utcnow()
        run.duration_sec = int((run.completed_at - run.started_at).total_seconds())
        run.stocks_processed = len(MACRO_INDICATORS) - len(failures)
        run.metadata_json = {**(run.metadata_json or {}), "total_rows": total_rows, "failures": failures}

    summary = Table(title="Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Indicators targeted", str(len(MACRO_INDICATORS)))
    summary.add_row("Successful", str(len(MACRO_INDICATORS) - len(failures)))
    summary.add_row("Failures", str(len(failures)))
    summary.add_row("Total rows inserted/updated", f"{total_rows:,}")
    console.print(summary)

    if failures:
        console.print("\n[yellow]Failures:[/yellow]")
        for f in failures:
            console.print(f"  • {f}")

    # Latest values per indicator
    with get_session() as s:
        subq = select(
            MacroDataDaily.indicator_code,
            func.max(MacroDataDaily.observation_date).label("max_date"),
        ).group_by(MacroDataDaily.indicator_code).subquery()
        rows = s.execute(
            select(
                MacroDataDaily.indicator_code,
                MacroDataDaily.indicator_name,
                MacroDataDaily.category,
                MacroDataDaily.observation_date,
                MacroDataDaily.value,
                MacroDataDaily.unit,
            ).join(
                subq,
                and_(
                    MacroDataDaily.indicator_code == subq.c.indicator_code,
                    MacroDataDaily.observation_date == subq.c.max_date,
                ),
            ).order_by(MacroDataDaily.category, MacroDataDaily.indicator_code)
        ).all()

    tbl = Table(title="Latest value per indicator")
    tbl.add_column("Code", style="cyan")
    tbl.add_column("Name")
    tbl.add_column("Category", style="magenta")
    tbl.add_column("Date")
    tbl.add_column("Value", justify="right", style="green")
    tbl.add_column("Unit", style="dim")
    for code, name, category, obs_date, value, unit in rows:
        tbl.add_row(code, name[:40], category, str(obs_date), f"{value:,.4f}" if value else "-", unit or "-")
    console.print(tbl)

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
