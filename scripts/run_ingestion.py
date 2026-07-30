"""Run the full daily ingestion pipeline (all 5 stages).

Usage:
    python scripts/run_ingestion.py              # incremental (last 5 days)
    python scripts/run_ingestion.py --days 30    # wider window

This is what you'll run daily at 8 AM IST once the prediction engine is built.
For now it just populates all data tables.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from src.common.logger import setup_logging
from src.db.models import (
    ArticleTicker,
    CorporateEvent,
    GlobalIndexDaily,
    MacroDataDaily,
    MarketDataDaily,
    NewsArticle,
    Run,
    RunType,
    Stock,
    StockUniverseHistory,
)
from src.db.session import get_session
from src.ingestion.pipeline import IngestionPipeline

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=5, help="Days to pull for incremental")
    return p.parse_args()


def summarize_stage(stage: str, data: dict) -> str:
    """One-line summary of stage stats for rich table."""
    if data.get("status") == "failed":
        return f"[red]{data.get('error', 'unknown')[:60]}[/red]"
    parts = []
    for k in ("stocks", "indices", "indicators", "rows_upserted",
              "articles_fetched", "articles_persisted", "ticker_mentions",
              "matched", "inserted"):
        if k in data and data[k] is not None:
            parts.append(f"{k}={data[k]}")
    return ", ".join(parts) or "ok"


def main() -> int:
    args = parse_args()
    console.print(f"[cyan]▶ Full ingestion pipeline (incremental: {args.days} days)[/cyan]\n")

    pipeline = IngestionPipeline(run_type=RunType.PREDICTION)
    stats = pipeline.run_all(days=args.days, label=f"daily_ingestion_{args.days}d")

    # Per-stage report
    table = Table(title=f"Pipeline run #{pipeline.run_id}")
    table.add_column("Stage", style="cyan")
    table.add_column("Status")
    table.add_column("Time")
    table.add_column("Details", style="green")

    stage_order = ["market_data", "global_indices", "macro", "news", "events"]
    for stage in stage_order:
        data = stats["stages"].get(stage, {})
        if not data:
            continue
        status = data.get("status", "?")
        status_str = "[green]✓[/green]" if status == "ok" else "[red]✗[/red]"
        duration = f"{data.get('duration_sec', 0):.1f}s"
        details = summarize_stage(stage, data)
        table.add_row(stage, status_str, duration, details)
    console.print(table)

    if stats["errors"]:
        console.print("\n[red]Errors:[/red]")
        for err in stats["errors"]:
            console.print(f"  • {err}")

    # Overall DB snapshot
    with get_session() as s:
        snapshot = {
            "stocks": s.scalar(select(func.count(Stock.id))) or 0,
            "stock_universe_history": s.scalar(select(func.count(StockUniverseHistory.id))) or 0,
            "market_data_daily": s.scalar(select(func.count(MarketDataDaily.id))) or 0,
            "global_indices_daily": s.scalar(select(func.count(GlobalIndexDaily.id))) or 0,
            "macro_data_daily": s.scalar(select(func.count(MacroDataDaily.id))) or 0,
            "news_articles": s.scalar(select(func.count(NewsArticle.id))) or 0,
            "article_tickers": s.scalar(select(func.count(ArticleTicker.id))) or 0,
            "corporate_events": s.scalar(select(func.count(CorporateEvent.id))) or 0,
            "runs": s.scalar(select(func.count(Run.id))) or 0,
        }

    snap_table = Table(title="Database snapshot (all tables)")
    snap_table.add_column("Table", style="cyan")
    snap_table.add_column("Rows", justify="right", style="green")
    for k, v in snapshot.items():
        snap_table.add_row(k, f"{v:,}")
    console.print(snap_table)

    total_time = sum(d.get("duration_sec", 0) for d in stats["stages"].values())
    if stats["errors"]:
        console.print(f"\n[yellow]⚠ Pipeline completed with {len(stats['errors'])} errors in {total_time:.1f}s[/yellow]")
        return 1
    console.print(f"\n[bold green]✓ Full pipeline complete in {total_time:.1f}s[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
