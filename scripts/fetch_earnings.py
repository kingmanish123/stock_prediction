"""Fetch upcoming corporate events (earnings, meetings, dividends) from NSE."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from src.common.logger import setup_logging
from src.db.models import CorporateEvent, EventStatus, Stock
from src.db.session import get_session
from src.ingestion.events.earnings import ingest_events

setup_logging()
console = Console()


def main() -> int:
    console.print(f"[cyan]▶ Fetching corporate events from NSE[/cyan]\n")

    result = ingest_events()

    summary = Table(title="Events ingestion")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Raw events from NSE (all-NSE)", f"{result['total']:,}")
    summary.add_row("Matched to Nifty 50", str(result["matched"]))
    summary.add_row("Inserted as new", str(result["inserted"]))
    console.print(summary)

    with get_session() as s:
        rows = s.execute(
            select(
                Stock.symbol,
                Stock.name,
                CorporateEvent.event_date,
                CorporateEvent.event_type,
                CorporateEvent.description,
            )
            .join(Stock, Stock.id == CorporateEvent.stock_id)
            .where(CorporateEvent.status == EventStatus.UPCOMING)
            .order_by(CorporateEvent.event_date)
            .limit(30)
        ).all()
        total = s.scalar(select(func.count(CorporateEvent.id))) or 0

    if rows:
        tbl = Table(title="Upcoming Nifty 50 corporate events")
        tbl.add_column("Symbol", style="cyan")
        tbl.add_column("Date", style="green")
        tbl.add_column("Type", style="magenta")
        tbl.add_column("Description", style="dim")
        for sym, name, ev_date, etype, desc in rows:
            tbl.add_row(sym, str(ev_date), etype.value if hasattr(etype, "value") else str(etype), (desc or "")[:60])
        console.print(tbl)
    else:
        console.print("[yellow]No upcoming Nifty 50 events found in NSE data right now[/yellow]")

    console.print(f"\n[green]✓ Total corporate_events rows in DB: {total:,}[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
