"""Build the feature matrix for a date range.

Usage:
    python scripts/build_features.py                  # last 30 trading days
    python scripts/build_features.py --from 2025-01-01 --to 2025-12-31
    python scripts/build_features.py --days 60

Writes: data/features/features_<start>_<end>.parquet
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table

from src.common.logger import setup_logging
from src.features.assembler import ALL_FEATURE_COLS, build_feature_matrix

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="from_date", type=str, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", type=str, help="YYYY-MM-DD")
    p.add_argument("--days", type=int, help="last N days (overrides --from/--to)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.days:
        end = date.today()
        start = end - timedelta(days=args.days)
    elif args.from_date and args.to_date:
        start = datetime.strptime(args.from_date, "%Y-%m-%d").date()
        end = datetime.strptime(args.to_date, "%Y-%m-%d").date()
    else:
        end = date.today()
        start = end - timedelta(days=45)

    console.print(f"[cyan]▶ Building features: {start} → {end}[/cyan]\n")

    df = build_feature_matrix(start, end, write_parquet=True)

    if df.empty:
        console.print("[red]No features produced[/red]")
        return 1

    summary = Table(title="Feature matrix")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Rows (stock × date)", f"{len(df):,}")
    summary.add_row("Columns total", str(len(df.columns)))
    summary.add_row("Stocks", str(df["stock_id"].nunique()))
    summary.add_row("Dates", str(df["trade_date"].nunique()))
    summary.add_row("Date range", f"{df['trade_date'].min().date()} → {df['trade_date'].max().date()}")
    summary.add_row("Feature columns", str(len(ALL_FEATURE_COLS)))
    console.print(summary)

    # Sample rows
    console.print("\n[cyan]Sample row (INFY, most recent date):[/cyan]")
    sample = df[df["symbol"] == "INFY"].sort_values("trade_date").tail(1)
    if not sample.empty:
        for col, val in sample.iloc[0].items():
            try:
                vstr = f"{val:.4f}" if isinstance(val, float) else str(val)
            except Exception:
                vstr = str(val)
            console.print(f"  {col}: [green]{vstr}[/green]")

    # Feature nullability check
    console.print("\n[cyan]Null rates per feature (lower = better):[/cyan]")
    null_rates = df[ALL_FEATURE_COLS].isna().mean().sort_values(ascending=False)
    nt = Table()
    nt.add_column("Feature", style="cyan")
    nt.add_column("Null %", style="green", justify="right")
    nt.add_column("Non-null rows", justify="right")
    for feat, null_rate in null_rates.items():
        non_null = int(len(df) * (1 - null_rate))
        color = "green" if null_rate < 0.05 else ("yellow" if null_rate < 0.3 else "red")
        nt.add_row(feat, f"[{color}]{null_rate*100:.1f}%[/{color}]", str(non_null))
    console.print(nt)

    return 0


if __name__ == "__main__":
    sys.exit(main())
