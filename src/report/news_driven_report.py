"""Markdown writer for news-driven daily predictions."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


def write_markdown_report(
    report_dir: Path,
    target_date: date,
    feature_date: date,
    themes_df: pd.DataFrame,
    picks_df: pd.DataFrame,
    total_cost_inr: float,
    llm_models: dict,
) -> Path:
    """Write a news-driven daily Markdown report.

    picks_df columns expected: rank, symbol, name, last_close, driving_theme,
    theme_direction, conviction, recommendation, primary_reasoning, key_risks (list).
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{target_date}.md"

    lines: list[str] = []
    lines.append(f"# Daily Predictions — {target_date}")
    lines.append("")
    lines.append(f"**Generated using data through**: {feature_date}  ")
    lines.append(f"**Bulk NLP model**: `{llm_models.get('bulk', '-')}`  ")
    lines.append(f"**Reasoning model**: `{llm_models.get('reasoning', '-')}`  ")
    lines.append(f"**Total LLM cost today**: ₹{total_cost_inr:.3f}")
    lines.append("")

    # Dominant themes section
    lines.append("## Dominant themes overnight")
    lines.append("")
    if themes_df.empty:
        lines.append("_No strong themes detected in pre-market window._")
    else:
        lines.append("| # | Theme | Direction | Strength | #Articles | #Sources |")
        lines.append("|---|-------|-----------|---------:|----------:|---------:|")
        for i, row in themes_df.iterrows():
            lines.append(
                f"| {i + 1} | **{row['theme_key']}** | {row['direction']} | "
                f"{row['strength']:.3f} | {row['article_count']} | {row['source_count']} |"
            )
    lines.append("")

    # Picks — trade setup only (pure numbers)
    lines.append(f"## {len(picks_df)} trade setups for {target_date}")
    lines.append("")
    lines.append("| # | Symbol | Buy at | Target | Stop-loss | Upside | Downside | R:R |")
    lines.append("|---|--------|-------:|-------:|----------:|-------:|---------:|----:|")
    for _, p in picks_df.iterrows():
        entry = p.get("last_close")
        target = p.get("predicted_high")
        stop = p.get("predicted_low")
        if entry and target and stop and entry > 0:
            upside_pct = (target - entry) / entry * 100
            downside_pct = (entry - stop) / entry * 100
            rr = upside_pct / downside_pct if downside_pct > 0 else 0
            lines.append(
                f"| {int(p['rank'])} | **{p['symbol']}** | "
                f"₹{entry:,.2f} | ₹{target:,.2f} | ₹{stop:,.2f} | "
                f"+{upside_pct:.2f}% | -{downside_pct:.2f}% | {rr:.2f} |"
            )
        else:
            lines.append(
                f"| {int(p['rank'])} | **{p['symbol']}** | — | — | — | — | — | — |"
            )
    lines.append("")

    # Optional deep reasoning section for those curious — collapsed/below
    lines.append("<details>")
    lines.append("<summary>Why these picks — driving context (click to expand)</summary>")
    lines.append("")
    for _, p in picks_df.iterrows():
        lines.append(f"**{int(p['rank'])}. {p['symbol']}** — {p.get('name', '')}")
        lines.append(f"- Driving theme: `{p.get('driving_theme', '—')}` ({p.get('theme_direction', '—')})")
        if p.get("primary_reasoning"):
            lines.append(f"- Context: {p['primary_reasoning']}")
        if p.get("key_risks"):
            lines.append(f"- Risks to watch:")
            for r in p["key_risks"][:3]:
                lines.append(f"  - {r}")
        lines.append("")
    lines.append("</details>")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_Not financial advice. System-generated. Validate against your own research._")

    path.write_text("\n".join(lines))
    return path
