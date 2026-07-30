"""Deep-dive analysis for a single day's predictions vs actuals.

For testing / learning: for each pick on a given date, shows:
  - Whether it was correct
  - Original reasoning / theme / conviction
  - News articles mentioning that stock in pre-market window
  - Recent technical state (momentum, RSI-ish indicators)
  - Markdown report saved for your notes

Usage:
    python scripts/analyze_day.py --date 2026-04-22
"""
import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from textwrap import shorten

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import and_, desc, func, select

from src.common.config import REPORTS_DIR
from src.common.logger import setup_logging
from src.db.models import (
    ArticleTicker,
    MarketDataDaily,
    NewsArticle,
    NewsTheme,
    Prediction,
    Stock,
    Validation,
)
from src.db.session import get_session

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=str, required=True, help="Target date YYYY-MM-DD")
    p.add_argument("--window-hours", type=int, default=24,
                   help="Pre-market news lookback window (hours)")
    return p.parse_args()


def _premarket_window(target_date: date, hours: int) -> tuple[datetime, datetime]:
    end = datetime.combine(target_date, time(8, 0))
    start = end - timedelta(hours=hours)
    return start, end


def _fetch_picks_and_actuals(target_date: date) -> list[dict]:
    """Get the top-10 picks + their validated actuals for the date."""
    with get_session() as s:
        rows = s.execute(
            select(
                Prediction.id.label("pred_id"),
                Prediction.buy_rank,
                Stock.id.label("stock_id"),
                Stock.symbol,
                Stock.name,
                Stock.sector,
                Prediction.direction,
                Prediction.confidence,
                Prediction.predicted_low,
                Prediction.predicted_high,
                Prediction.model_version,
                Prediction.reasoning,
                Prediction.model_outputs,
                Validation.actual_open,
                Validation.actual_close,
                Validation.actual_high,
                Validation.actual_low,
                Validation.actual_return_pct,
                Validation.direction_correct,
                Validation.range_hit,
            )
            .join(Stock, Stock.id == Prediction.stock_id)
            .outerjoin(Validation, Validation.prediction_id == Prediction.id)
            .where(Prediction.run_date == target_date)
            .where(Prediction.buy_rank.isnot(None))
            .order_by(Prediction.buy_rank)
        ).all()

    out = []
    for r in rows:
        mo = r.model_outputs or {}
        out.append({
            "pred_id": r.pred_id,
            "rank": r.buy_rank,
            "stock_id": r.stock_id,
            "symbol": r.symbol,
            "name": r.name,
            "sector": r.sector,
            "direction": r.direction.value if hasattr(r.direction, "value") else str(r.direction),
            "confidence": float(r.confidence) if r.confidence is not None else None,
            "predicted_low": float(r.predicted_low) if r.predicted_low is not None else None,
            "predicted_high": float(r.predicted_high) if r.predicted_high is not None else None,
            "reasoning": r.reasoning,
            "model_version": r.model_version,
            "source": mo.get("source"),
            "theme": mo.get("theme_key"),
            "theme_direction": mo.get("theme_direction"),
            "conviction": mo.get("conviction"),
            "recommendation": mo.get("recommendation"),
            "supporting_factors": mo.get("supporting_factors", []),
            "key_risks": mo.get("key_risks", []),
            "actual_open": float(r.actual_open) if r.actual_open is not None else None,
            "actual_close": float(r.actual_close) if r.actual_close is not None else None,
            "actual_high": float(r.actual_high) if r.actual_high is not None else None,
            "actual_low": float(r.actual_low) if r.actual_low is not None else None,
            "actual_return_pct": float(r.actual_return_pct) if r.actual_return_pct is not None else None,
            "direction_correct": r.direction_correct,
            "range_hit": r.range_hit,
        })
    return out


def _fetch_news_for_stock(stock_id: int, window_start: datetime, window_end: datetime) -> list[dict]:
    """News articles mentioning stock within pre-market window."""
    with get_session() as s:
        rows = s.execute(
            select(
                NewsArticle.title,
                NewsArticle.source,
                NewsArticle.published_at,
                NewsArticle.url,
                NewsTheme.theme_key,
                NewsTheme.direction.label("nt_direction"),
                NewsTheme.magnitude,
                NewsTheme.reasoning.label("nt_reasoning"),
            )
            .join(ArticleTicker, ArticleTicker.article_id == NewsArticle.id)
            .outerjoin(NewsTheme, NewsTheme.article_id == NewsArticle.id)
            .where(
                ArticleTicker.stock_id == stock_id,
                NewsArticle.published_at >= window_start,
                NewsArticle.published_at < window_end,
            )
            .order_by(desc(NewsArticle.published_at))
        ).all()

    return [{
        "title": r.title,
        "source": r.source,
        "published_at": r.published_at,
        "url": r.url,
        "theme_key": r.theme_key,
        "theme_direction": r.nt_direction.value if hasattr(r.nt_direction, "value") else str(r.nt_direction),
        "magnitude": float(r.magnitude) if r.magnitude is not None else None,
        "theme_reasoning": r.nt_reasoning,
    } for r in rows]


def _technical_snapshot(stock_id: int, as_of: date) -> dict:
    """Recent price/volume state: last close, 5d/20d returns, volume ratio."""
    lookback = as_of - timedelta(days=45)
    with get_session() as s:
        rows = s.execute(
            select(MarketDataDaily.trade_date, MarketDataDaily.close, MarketDataDaily.volume)
            .where(
                MarketDataDaily.stock_id == stock_id,
                MarketDataDaily.trade_date >= lookback,
                MarketDataDaily.trade_date < as_of,  # strictly BEFORE target date
            )
            .order_by(MarketDataDaily.trade_date)
        ).all()

    if not rows or len(rows) < 2:
        return {}
    closes = [float(r.close) for r in rows]
    volumes = [int(r.volume) for r in rows if r.volume]
    last = closes[-1]
    ret_5d = (last / closes[-6] - 1) if len(closes) >= 6 else None
    ret_20d = (last / closes[-21] - 1) if len(closes) >= 21 else None
    vol_avg_20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else None
    vol_ratio = volumes[-1] / vol_avg_20 if (volumes and vol_avg_20 and vol_avg_20 > 0) else None
    return {
        "last_close_pre": round(last, 2),
        "return_5d_pct": round(ret_5d * 100, 2) if ret_5d is not None else None,
        "return_20d_pct": round(ret_20d * 100, 2) if ret_20d is not None else None,
        "volume_ratio_20d": round(vol_ratio, 2) if vol_ratio else None,
    }


def _hypothesize_miss(pick: dict, news: list[dict], tech: dict) -> list[str]:
    """Heuristic hypotheses for why a pick didn't move as predicted."""
    hints: list[str] = []
    ret = pick.get("actual_return_pct")
    direction = pick.get("direction")
    if ret is None:
        return hints

    # Hypothesis 1: already-rallied stock = profit booking
    r5 = tech.get("return_5d_pct")
    r20 = tech.get("return_20d_pct")
    if direction == "UP" and ret < 0:
        if r5 and r5 > 5:
            hints.append(
                f"Already rallied {r5:+.1f}% over 5 days before prediction → "
                f"likely profit booking / mean reversion, not trend continuation"
            )
        if r20 and r20 > 15:
            hints.append(
                f"Up {r20:+.1f}% over 20 days → trade may be crowded; exhaustion risk"
            )

    # Hypothesis 2: no news support
    news_count = len(news)
    if direction == "UP" and ret < 0 and news_count == 0:
        hints.append(
            "No pre-market news mentioned this stock specifically — "
            "theme-only pick with no stock-level catalyst"
        )

    # Hypothesis 3: conflicting sentiment in news
    if news:
        neg_count = sum(1 for n in news if n.get("theme_direction") == "bearish")
        pos_count = sum(1 for n in news if n.get("theme_direction") == "bullish")
        if direction == "UP" and neg_count > pos_count:
            hints.append(
                f"Pre-market news had {neg_count} bearish vs {pos_count} bullish — "
                f"aggregator may have over-weighted bullish theme"
            )

    # Hypothesis 4: low volume
    vr = tech.get("volume_ratio_20d")
    if vr and vr < 0.7 and direction == "UP" and ret < 0:
        hints.append(
            f"Volume ratio {vr:.2f} (below average) — no institutional accumulation "
            f"confirming the bullish thesis"
        )

    # Hypothesis 5: range too wide — stock moved beyond predicted band
    actual_ret_abs = abs(ret)
    if pick.get("predicted_high") and pick.get("predicted_low"):
        # Was actual H/L outside predicted range?
        if pick.get("actual_high") and pick["actual_high"] > pick["predicted_high"] * 1.01:
            hints.append(
                f"Actual high ₹{pick['actual_high']:.2f} exceeded predicted high "
                f"₹{pick['predicted_high']:.2f} — model underestimated upside volatility"
            )
        if pick.get("actual_low") and pick["actual_low"] < pick["predicted_low"] * 0.99:
            hints.append(
                f"Actual low ₹{pick['actual_low']:.2f} broke predicted floor "
                f"₹{pick['predicted_low']:.2f} — stop-loss would have triggered"
            )

    if not hints:
        hints.append(
            "No obvious heuristic match — manual news research needed. "
            "Common causes: sector rotation, global risk-off, company-specific surprise."
        )
    return hints


def _render_markdown(
    target_date: date, picks: list[dict], news_by_stock: dict[int, list[dict]],
    tech_by_stock: dict[int, dict],
) -> Path:
    """Write analysis as markdown for offline notes + annotation."""
    out_dir = REPORTS_DIR / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{target_date}.md"

    lines = [
        f"# Day Analysis — {target_date}",
        "",
        f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
    ]

    # Summary
    total = len([p for p in picks if p.get("actual_return_pct") is not None])
    correct = len([p for p in picks if p.get("direction_correct")])
    avg_ret = (
        sum(p["actual_return_pct"] for p in picks if p.get("actual_return_pct") is not None) / total
        if total else 0
    )
    lines += [
        "## Summary",
        "",
        f"- **Picks with actuals**: {total} of {len(picks)}",
        f"- **Direction correct**: {correct} / {total} ({correct/max(total,1):.1%})",
        f"- **Avg return**: {avg_ret:+.3f}%",
        "",
    ]

    hits = [p for p in picks if p.get("direction_correct") is True]
    misses = [p for p in picks if p.get("direction_correct") is False]

    if hits:
        lines += ["## ✅ Hits", ""]
        for p in hits:
            lines += [
                f"### #{p['rank']} {p['symbol']} — {p.get('name', '')}",
                "",
                f"- **Return**: {p.get('actual_return_pct', 0):+.3f}%",
                f"- **Source**: {p.get('source', '—')}  ·  **Theme**: `{p.get('theme', '—')}`",
                f"- **Conviction**: {p.get('conviction', '—')}/10  ·  **Rec**: {p.get('recommendation', '—')}",
                f"- **Reasoning**: {p.get('reasoning') or '—'}",
                "",
            ]

    if misses:
        lines += ["## ❌ Misses — deep dive", ""]
        for p in misses:
            tech = tech_by_stock.get(p["stock_id"], {})
            news = news_by_stock.get(p["stock_id"], [])
            lines += [
                f"### #{p['rank']} {p['symbol']} — {p.get('name', '')}",
                "",
                f"- **Actual return**: {p.get('actual_return_pct', 0):+.3f}%  "
                f"(open ₹{p.get('actual_open', 0):.2f} → close ₹{p.get('actual_close', 0):.2f})",
                f"- **Predicted**: {p['direction']} with conviction {p.get('conviction', '—')}/10 (theme: `{p.get('theme', '—')}`)",
                f"- **Our reasoning was**: {p.get('reasoning') or '—'}",
                "",
                "**Technical state BEFORE this day:**",
            ]
            if tech:
                for k, v in tech.items():
                    lines.append(f"  - {k}: {v}")
            else:
                lines.append("  - (no data)")
            lines.append("")

            lines.append(f"**News mentioning {p['symbol']} in pre-market window** ({len(news)} articles):")
            if news:
                for n in news[:8]:
                    theme_str = f" [theme: {n['theme_key']} {n.get('theme_direction')}]" if n.get("theme_key") else ""
                    lines.append(
                        f"  - [{n['published_at']}] **{n['source']}**{theme_str}  \n"
                        f"    {n['title']}"
                    )
                if len(news) > 8:
                    lines.append(f"  - …and {len(news)-8} more")
            else:
                lines.append("  - _(no pre-market news found mentioning this stock)_")
            lines.append("")

            lines.append("**Automated hypotheses for why it moved opposite:**")
            for h in _hypothesize_miss(p, news, tech):
                lines.append(f"  - {h}")
            lines.append("")
            lines.append("**Your manual research notes:**")
            lines.append("")
            lines.append("> _TODO: Research news on this stock from " +
                         f"{target_date - timedelta(days=2)} to {target_date + timedelta(days=1)}. " +
                         "Note real cause of the move. What pattern would have helped predict correctly?_")
            lines.append("")

    lines += [
        "---",
        "",
        "## Learnings for system improvement",
        "",
        "_TODO: After reviewing misses, note patterns that could become:_",
        "_  - New features (e.g., 'consecutive_up_days', 'news_sentiment_recent')_",
        "_  - LLM prompt additions (e.g., 'check if stock already up >5% in 5d')_",
        "_  - New canonical themes (e.g., 'profit_booking_after_rally')_",
    ]

    path.write_text("\n".join(lines))
    return path


def main() -> int:
    args = parse_args()
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    window_start, window_end = _premarket_window(target_date, args.window_hours)

    console.print(Panel.fit(
        f"[bold]Day Analysis — {target_date}[/bold]\n"
        f"Pre-market window: {window_start} → {window_end}",
        border_style="cyan",
    ))

    picks = _fetch_picks_and_actuals(target_date)
    if not picks:
        console.print(f"[red]No predictions found for {target_date}[/red]")
        return 1

    # Fetch news + technicals for each pick
    news_by_stock: dict[int, list[dict]] = {}
    tech_by_stock: dict[int, dict] = {}
    for p in picks:
        news_by_stock[p["stock_id"]] = _fetch_news_for_stock(
            p["stock_id"], window_start, window_end
        )
        tech_by_stock[p["stock_id"]] = _technical_snapshot(p["stock_id"], target_date)

    # Summary
    total = len([p for p in picks if p.get("actual_return_pct") is not None])
    correct = len([p for p in picks if p.get("direction_correct")])
    avg_ret = (
        sum(p["actual_return_pct"] for p in picks if p.get("actual_return_pct") is not None) / total
        if total else 0
    )

    summary = Table(title=f"Picks summary — {target_date}")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Total picks", str(len(picks)))
    summary.add_row("With validated actuals", str(total))
    summary.add_row("Direction correct", f"{correct} / {total}")
    summary.add_row("Accuracy", f"{correct/max(total,1):.3f}")
    summary.add_row("Avg return", f"{avg_ret:+.3f}%")
    console.print(summary)

    # Per-pick table
    tbl = Table(title="All picks vs actuals")
    tbl.add_column("#", style="dim")
    tbl.add_column("Symbol", style="cyan bold")
    tbl.add_column("Src", style="yellow")
    tbl.add_column("Theme", style="cyan")
    tbl.add_column("Conv", justify="right")
    tbl.add_column("Predicted", style="magenta")
    tbl.add_column("Actual return", justify="right")
    tbl.add_column("Hit?", style="bold")
    tbl.add_column("News articles")

    for p in picks:
        ret = p.get("actual_return_pct")
        ret_str = f"{ret:+.3f}%" if ret is not None else "—"
        ret_color = "green" if p.get("direction_correct") else "red"
        hit = ("[green]✓[/green]" if p.get("direction_correct") else
               "[red]✗[/red]" if p.get("direction_correct") is False else "—")
        nc = len(news_by_stock.get(p["stock_id"], []))
        src = p.get("source") or "—"
        tbl.add_row(
            str(p["rank"]),
            p["symbol"],
            src[:6],
            (p.get("theme") or "—")[:18],
            f"{p.get('conviction', '—')}",
            p["direction"],
            f"[{ret_color}]{ret_str}[/{ret_color}]",
            hit,
            str(nc),
        )
    console.print(tbl)

    # Misses deep-dive on terminal
    misses = [p for p in picks if p.get("direction_correct") is False]
    if misses:
        console.print()
        console.print(
            Panel.fit(
                f"[bold]Miss deep-dive — {len(misses)} picks to analyze[/bold]",
                border_style="red",
            )
        )
        for p in misses:
            tech = tech_by_stock.get(p["stock_id"], {})
            news = news_by_stock.get(p["stock_id"], [])

            console.print(f"\n[bold cyan]#{p['rank']} {p['symbol']} — {p.get('name', '')}[/bold cyan]")
            console.print(
                f"  Actual: {p.get('actual_return_pct', 0):+.3f}%  "
                f"(open ₹{p.get('actual_open', 0):.2f} → close ₹{p.get('actual_close', 0):.2f})"
            )
            console.print(
                f"  Predicted: {p['direction']}  conv={p.get('conviction', '—')}/10  "
                f"theme={p.get('theme', '—')}  src={p.get('source', '—')}"
            )
            if p.get("reasoning"):
                console.print(f"  Our reasoning: [dim]{shorten(p['reasoning'], 200, placeholder='…')}[/dim]")

            if tech:
                console.print(f"  Technical state before day: "
                              f"close ₹{tech.get('last_close_pre')}  "
                              f"5d {tech.get('return_5d_pct')}%  "
                              f"20d {tech.get('return_20d_pct')}%  "
                              f"vol-ratio {tech.get('volume_ratio_20d')}")

            console.print(f"  [cyan]Pre-market news ({len(news)}):[/cyan]")
            if news:
                for n in news[:5]:
                    theme_str = f" [magenta][{n['theme_key']}/{n['theme_direction']}][/magenta]" if n.get("theme_key") else ""
                    console.print(
                        f"    [{n['source']} {n['published_at']}]{theme_str}  "
                        f"{shorten(n['title'], 90, placeholder='…')}"
                    )
            else:
                console.print("    [yellow](no pre-market news for this stock)[/yellow]")

            hints = _hypothesize_miss(p, news, tech)
            console.print(f"  [bold yellow]Auto-hypotheses:[/bold yellow]")
            for h in hints:
                console.print(f"    • {h}")

    # Write markdown
    md_path = _render_markdown(target_date, picks, news_by_stock, tech_by_stock)
    console.print(f"\n[green]✓ Markdown report: {md_path}[/green]")
    console.print(
        "[dim]Open in editor. Add your notes under 'Your manual research notes' for each miss. "
        "Then note patterns in 'Learnings for system improvement' section.[/dim]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
