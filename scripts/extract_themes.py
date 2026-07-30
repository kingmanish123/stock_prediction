"""Batch-extract themes from news articles via Gemini.

Processes all news_articles that don't yet have a news_themes row for the
active bulk LLM model. Idempotent — re-run any time.

Usage:
    python scripts/extract_themes.py              # all pending
    python scripts/extract_themes.py --limit 30   # cap for dev
    python scripts/extract_themes.py --rate-sec 0.5  # sleep between calls
"""
import argparse
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from sqlalchemy import desc, func, select

from src.common import config
from src.common.logger import setup_logging
from src.db.models import NewsTheme
from src.db.session import get_session
from src.nlp.theme_extractor import ThemeExtractor, pending_articles, persist

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="Cap number of articles")
    p.add_argument("--rate-sec", type=float, default=0.2, help="Sleep between LLM calls")
    p.add_argument("--batch-persist", type=int, default=10, help="Flush to DB every N extractions")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    extractor = ThemeExtractor()
    console.print(f"[cyan]▶ LLM: {extractor.model_name}[/cyan]")

    pending = pending_articles(limit=args.limit)
    if not pending:
        console.print("[yellow]No articles pending extraction.[/yellow]")
        return 0

    console.print(f"  Pending articles: [bold]{len(pending)}[/bold]")

    successes = 0
    failures = 0
    total_cost_inr = Decimal("0")
    total_tokens_in = 0
    total_tokens_out = 0
    buffer: list = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Extracting", total=len(pending))

        for article in pending:
            title_short = article.title[:50] if article.title else ""
            progress.update(task, description=f"[cyan]#{article.id}[/cyan] {title_short}")

            result = extractor.extract(article)
            if result:
                buffer.append(result)
                successes += 1
                total_cost_inr += result.cost_inr
                total_tokens_in += result.tokens_in
                total_tokens_out += result.tokens_out
            else:
                failures += 1

            if len(buffer) >= args.batch_persist:
                persist(buffer, extractor.model_name)
                buffer = []

            progress.advance(task)
            if args.rate_sec > 0:
                time.sleep(args.rate_sec)

    # Flush remaining
    if buffer:
        persist(buffer, extractor.model_name)

    # Summary
    summary = Table(title="Extraction complete")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Articles processed", str(len(pending)))
    summary.add_row("Successful extractions", str(successes))
    summary.add_row("Failures", str(failures))
    summary.add_row("Total input tokens", f"{total_tokens_in:,}")
    summary.add_row("Total output tokens", f"{total_tokens_out:,}")
    summary.add_row("Total cost", f"₹{total_cost_inr:.4f}")
    summary.add_row("Avg cost per article", f"₹{total_cost_inr / max(successes, 1):.4f}")
    console.print(summary)

    # Quality spot-check — sample themes
    with get_session() as s:
        total_themes = s.scalar(select(func.count(NewsTheme.id))) or 0

        # Theme distribution
        theme_rows = s.execute(
            select(NewsTheme.theme_key, func.count(NewsTheme.id).label("cnt"))
            .group_by(NewsTheme.theme_key)
            .order_by(desc("cnt"))
            .limit(15)
        ).all()

        # Direction distribution
        dir_rows = s.execute(
            select(NewsTheme.direction, func.count(NewsTheme.id).label("cnt"))
            .group_by(NewsTheme.direction)
            .order_by(desc("cnt"))
        ).all()

        # Recent high-magnitude bullish extractions (spot check)
        from src.db.models import NewsArticle
        recent_strong = s.execute(
            select(
                NewsTheme.theme_key,
                NewsTheme.theme_label,
                NewsTheme.direction,
                NewsTheme.magnitude,
                NewsTheme.confidence,
                NewsTheme.validated_tickers,
                NewsArticle.title,
            )
            .join(NewsArticle, NewsArticle.id == NewsTheme.article_id)
            .where(NewsTheme.direction != "neutral")
            .where(NewsTheme.magnitude >= 0.3)
            .order_by(desc(NewsTheme.magnitude * NewsTheme.confidence))
            .limit(10)
        ).all()

    console.print(f"\n[green]Total themes in DB: {total_themes:,}[/green]\n")

    tt = Table(title="Top theme keys")
    tt.add_column("Theme", style="cyan")
    tt.add_column("Count", style="green", justify="right")
    for theme, cnt in theme_rows:
        tt.add_row(theme or "(none)", str(cnt))
    console.print(tt)

    dt = Table(title="Direction distribution")
    dt.add_column("Direction", style="cyan")
    dt.add_column("Count", style="green", justify="right")
    for direction, cnt in dir_rows:
        dir_val = direction.value if hasattr(direction, "value") else str(direction)
        dt.add_row(dir_val, str(cnt))
    console.print(dt)

    if recent_strong:
        rt = Table(title="Strongest 10 signals (magnitude × confidence)")
        rt.add_column("Theme", style="cyan")
        rt.add_column("Dir", style="magenta")
        rt.add_column("Mag", justify="right")
        rt.add_column("Conf", justify="right")
        rt.add_column("Tickers", style="yellow")
        rt.add_column("Title", style="dim")
        for theme, label, direction, mag, conf, tickers, title in recent_strong:
            dir_val = direction.value if hasattr(direction, "value") else str(direction)
            tickers_str = ", ".join(tickers[:4]) if tickers else "-"
            if tickers and len(tickers) > 4:
                tickers_str += f" +{len(tickers) - 4}"
            rt.add_row(
                theme or "?",
                dir_val,
                f"{mag:.2f}" if mag else "-",
                f"{conf:.2f}" if conf else "-",
                tickers_str,
                (title or "")[:55],
            )
        console.print(rt)

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
