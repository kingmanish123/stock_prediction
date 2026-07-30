"""Source-level validation — does news-driven beat XGBoost fallback?

This is the critical measurement for Week 7. Splits historical predictions by
their `model_outputs.source` field (news_driven vs xgboost_fallback) and
compares accuracy + returns. This tells us whether the LLM reasoning layer
actually adds alpha over the pure ML baseline.

Usage:
    python scripts/validate_by_source.py                  # all validated days
    python scripts/validate_by_source.py --days 30        # rolling last N days
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import case, func, select

from src.common.logger import setup_logging
from src.db.models import Prediction, Stock, Validation
from src.db.session import get_session

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, help="Limit to last N days of run_date")
    p.add_argument("--buy-only", action="store_true", default=True,
                   help="Only consider predictions with buy_rank set (default true)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    console.print(Panel.fit("Source-level Validation Report", border_style="cyan"))

    # Base query: all predictions with validations
    cutoff = date.today() - timedelta(days=args.days) if args.days else None

    with get_session() as s:
        filters = [Validation.id.isnot(None)]
        if args.buy_only:
            filters.append(Prediction.buy_rank.isnot(None))
        if cutoff:
            filters.append(Prediction.run_date >= cutoff)

        # Per-source breakdown (source is in model_outputs JSON)
        rows = s.execute(
            select(
                Prediction.run_date,
                Prediction.buy_rank,
                Stock.symbol,
                func.json_extract(Prediction.model_outputs, "$.source").label("source"),
                func.json_extract(Prediction.model_outputs, "$.theme_key").label("theme"),
                func.json_extract(Prediction.model_outputs, "$.conviction").label("conviction"),
                Validation.actual_return_pct,
                Validation.direction_correct,
            )
            .join(Prediction, Prediction.id == Validation.prediction_id)
            .join(Stock, Stock.id == Prediction.stock_id)
            .where(*filters)
            .order_by(Prediction.run_date, Prediction.buy_rank)
        ).all()

    if not rows:
        console.print(
            f"[yellow]No validated BUY picks found "
            f"{'in last ' + str(args.days) + ' days' if args.days else ''}[/yellow]"
        )
        return 0

    # Group by source
    by_source: dict[str, list] = {}
    for r in rows:
        src_raw = r.source
        src = str(src_raw).strip('"') if src_raw else "unknown"
        by_source.setdefault(src, []).append(r)

    total_picks = len(rows)
    console.print(f"  Total BUY picks validated: [bold]{total_picks}[/bold]")
    for src, rs in by_source.items():
        console.print(f"    - {src}: {len(rs)} picks")

    # Accuracy by source
    summary_table = Table(title="Accuracy by pick source")
    summary_table.add_column("Source", style="cyan bold")
    summary_table.add_column("Picks", justify="right")
    summary_table.add_column("Direction correct", justify="right")
    summary_table.add_column("Accuracy", justify="right", style="green")
    summary_table.add_column("Avg return", justify="right")
    summary_table.add_column("Best", justify="right", style="green")
    summary_table.add_column("Worst", justify="right", style="red")

    for src, rs in sorted(by_source.items()):
        correct = sum(1 for r in rs if r.direction_correct)
        acc = correct / len(rs) if rs else 0
        returns = [float(r.actual_return_pct or 0) for r in rs]
        avg_ret = sum(returns) / len(returns) if returns else 0
        best = max(returns) if returns else 0
        worst = min(returns) if returns else 0
        summary_table.add_row(
            src,
            str(len(rs)),
            f"{correct}/{len(rs)}",
            f"{acc:.3f}",
            f"{avg_ret:+.3f}%",
            f"{best:+.3f}%",
            f"{worst:+.3f}%",
        )
    console.print(summary_table)

    # Per-date breakdown — helps see day-to-day dynamics
    console.print()
    perdate_table = Table(title="Day-by-day performance")
    perdate_table.add_column("Date", style="cyan")
    perdate_table.add_column("Source", style="magenta")
    perdate_table.add_column("Picks")
    perdate_table.add_column("Correct", justify="right")
    perdate_table.add_column("Avg return", justify="right", style="green")

    perdate_rows: dict[tuple[date, str], list] = {}
    for r in rows:
        src = str(r.source).strip('"') if r.source else "unknown"
        perdate_rows.setdefault((r.run_date, src), []).append(r)

    for (rdate, src), rs in sorted(perdate_rows.items()):
        correct = sum(1 for r in rs if r.direction_correct)
        returns = [float(r.actual_return_pct or 0) for r in rs]
        avg_ret = sum(returns) / len(returns) if returns else 0
        perdate_table.add_row(
            str(rdate), src, str(len(rs)),
            f"{correct}/{len(rs)}",
            f"{avg_ret:+.3f}%",
        )
    console.print(perdate_table)

    # Top picks drill-down (best + worst)
    console.print()
    best_picks = sorted(rows, key=lambda r: float(r.actual_return_pct or 0), reverse=True)[:5]
    worst_picks = sorted(rows, key=lambda r: float(r.actual_return_pct or 0))[:5]

    dd = Table(title="5 best actual returns")
    dd.add_column("Date", style="cyan")
    dd.add_column("Rank", style="dim")
    dd.add_column("Symbol", style="cyan bold")
    dd.add_column("Source")
    dd.add_column("Theme", style="yellow")
    dd.add_column("Conv", justify="right")
    dd.add_column("Actual", justify="right", style="green")
    dd.add_column("Correct?")
    for r in best_picks:
        src = str(r.source).strip('"') if r.source else "-"
        theme = str(r.theme).strip('"') if r.theme else "-"
        conv = str(r.conviction).strip('"') if r.conviction else "-"
        ret = f"{float(r.actual_return_pct or 0):+.2f}%"
        ok = "[green]✓[/green]" if r.direction_correct else "[red]✗[/red]"
        dd.add_row(str(r.run_date), str(r.buy_rank), r.symbol, src, theme[:18], conv, ret, ok)
    console.print(dd)

    wt = Table(title="5 worst actual returns")
    wt.add_column("Date", style="cyan")
    wt.add_column("Rank", style="dim")
    wt.add_column("Symbol", style="cyan bold")
    wt.add_column("Source")
    wt.add_column("Theme", style="yellow")
    wt.add_column("Conv", justify="right")
    wt.add_column("Actual", justify="right", style="red")
    wt.add_column("Correct?")
    for r in worst_picks:
        src = str(r.source).strip('"') if r.source else "-"
        theme = str(r.theme).strip('"') if r.theme else "-"
        conv = str(r.conviction).strip('"') if r.conviction else "-"
        ret = f"{float(r.actual_return_pct or 0):+.2f}%"
        ok = "[green]✓[/green]" if r.direction_correct else "[red]✗[/red]"
        wt.add_row(str(r.run_date), str(r.buy_rank), r.symbol, src, theme[:18], conv, ret, ok)
    console.print(wt)

    # Honest verdict
    console.print()
    if len(by_source) >= 2:
        news = by_source.get("news_driven", [])
        xgb = by_source.get("xgboost_fallback", [])
        if news and xgb:
            n_acc = sum(1 for r in news if r.direction_correct) / len(news)
            x_acc = sum(1 for r in xgb if r.direction_correct) / len(xgb)
            n_ret = sum(float(r.actual_return_pct or 0) for r in news) / len(news)
            x_ret = sum(float(r.actual_return_pct or 0) for r in xgb) / len(xgb)
            verdict = "news-driven wins" if n_ret > x_ret else (
                "XGBoost wins" if x_ret > n_ret else "tied"
            )
            console.print(Panel(
                f"[bold]Comparison:[/bold]\n"
                f"  News-driven: {n_acc:.3f} accuracy, {n_ret:+.3f}% avg return ({len(news)} picks)\n"
                f"  XGBoost   : {x_acc:.3f} accuracy, {x_ret:+.3f}% avg return ({len(xgb)} picks)\n"
                f"  Difference: {n_ret - x_ret:+.3f} pp return spread\n\n"
                f"[bold]Verdict: {verdict}[/bold]\n"
                f"[dim](Very small sample — need 30+ days for statistical significance)[/dim]",
                title="Alpha check",
                border_style="green" if n_ret > x_ret else "yellow",
            ))
    else:
        console.print(
            Panel(
                "[yellow]Only one source so far. Run more days to compare news-driven vs XGBoost.[/yellow]",
                border_style="yellow",
            )
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
