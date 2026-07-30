"""One-time: download Upstox instruments master + map to our stocks table.

Upstox uses instrument keys like `NSE_EQ|INE009A01021` (ISIN-based) for API calls.
We match our `stocks` rows by ISIN (primary) or symbol (fallback) and store
the resulting instrument_key in `stocks.upstox_instrument_key`.

Re-run this whenever: new stocks are added, or Upstox instrument master changes
(quarterly-ish).

Usage:
    python scripts/fetch_upstox_instruments.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from src.broker.instrument_map import seed_upstox_mapping
from src.common.logger import setup_logging
from src.db.models import Stock
from src.db.session import get_session

setup_logging()
console = Console()


def main() -> int:
    console.print(
        "[cyan]▶ Downloading Upstox instruments master (~20 MB gzipped)…[/cyan]"
    )
    try:
        matched, total = seed_upstox_mapping()
    except Exception as e:
        console.print(f"[red]Mapping failed: {e}[/red]")
        return 1

    summary = Table(title="Instrument mapping summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Stocks in catalog", str(total))
    summary.add_row("Mapped to Upstox", str(matched))
    summary.add_row("Unmapped", str(total - matched))
    console.print(summary)

    # Show first 5 mapped rows as sanity check
    with get_session() as s:
        sample = s.execute(
            select(Stock.symbol, Stock.isin, Stock.upstox_instrument_key)
            .where(Stock.upstox_instrument_key.isnot(None))
            .limit(5)
        ).all()

    if sample:
        sample_tbl = Table(title="Sample mappings")
        sample_tbl.add_column("Symbol", style="cyan")
        sample_tbl.add_column("ISIN")
        sample_tbl.add_column("Upstox instrument_key", style="green")
        for r in sample:
            sample_tbl.add_row(r.symbol, r.isin or "—", r.upstox_instrument_key)
        console.print(sample_tbl)

    console.print("\n[green]✓ Done.[/green] Live quotes via Upstox now available in live_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
