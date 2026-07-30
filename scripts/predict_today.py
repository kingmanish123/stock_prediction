"""News-driven daily top-10 BUY pipeline.

User spec: every trading day, output top 10 BUY picks.

Flow:
  1. Aggregate overnight news themes
  2. Split themes by direction (bullish vs bearish)
  3. Fan out bullish themes → candidate stocks (these are the BUY source)
  4. Run Claude deep reasoning on top bullish candidates
  5. Rank by final_score × conviction
  6. If fewer than 10, supplement with XGBoost top prob_up picks
  7. Display + persist + write Markdown
  8. Also show bearish themes as "watch-list" info (not in the 10 picks)
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from src.common import config
from src.common.logger import setup_logging
from src.db.models import (
    MarketDataDaily,
    Prediction,
    Run,
    RunStatus,
    RunType,
)
from src.db.session import get_session
from src.ml.range_predictor import load_active_range_models, predict_ranges_for_stocks
from src.ml.trade_levels import compute_atr, derive_trade_levels
from src.ml.xgboost_predictor import xgboost_top_buys
from src.nlp.stock_fanout import (
    find_all_candidates,
    merge_candidates,
)
from src.nlp.stock_reasoner import (
    StockReasoner,
    StockReasoning,
    _fetch_stock_news_snippets,
    _fetch_technical_snapshot,
    is_bearish_news_veto,
)
from src.nlp.theme_aggregator import aggregate_themes_for_date
from src.report.news_driven_report import write_markdown_report

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--target-date", type=str, help="Override target trading day YYYY-MM-DD")
    p.add_argument(
        "--max-claude-candidates", type=int, default=15,
        help="Max bullish candidates to send to Claude (cost control)",
    )
    p.add_argument("--top-n", type=int, default=10, help="Final BUY picks to output")
    return p.parse_args()


def _next_trading_day(d: date) -> date:
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def _determine_dates(override: str | None) -> tuple[date, date]:
    with get_session() as s:
        feature_date = s.scalar(select(func.max(MarketDataDaily.trade_date)))
    if override:
        target_date = datetime.strptime(override, "%Y-%m-%d").date()
        with get_session() as s:
            feature_date = s.scalar(
                select(func.max(MarketDataDaily.trade_date))
                .where(MarketDataDaily.trade_date < target_date)
            ) or feature_date
    else:
        if feature_date is None:
            raise RuntimeError("No market_data_daily — run ingestion first")
        target_date = _next_trading_day(feature_date)
    return feature_date, target_date


def _format_conv(conv: int) -> str:
    color = "green" if conv >= 7 else ("yellow" if conv >= 5 else "red")
    return f"[{color}]{conv}/10[/{color}]"


def main() -> int:
    args = parse_args()
    feature_date, target_date = _determine_dates(args.target_date)

    console.print(
        Panel.fit(
            f"Feature date: [bold cyan]{feature_date}[/bold cyan] "
            f"({feature_date.strftime('%A')})\n"
            f"Target date:  [bold green]{target_date}[/bold green] "
            f"({target_date.strftime('%A')})",
            title="Daily Top-10 BUY (News-Driven)",
            border_style="cyan",
        )
    )

    # 1. Aggregate themes ─────────────────────────────────────────────
    console.print("\n[cyan]▶ Aggregating overnight news themes[/cyan]")
    all_themes = aggregate_themes_for_date(target_date, min_articles=1)
    all_themes = [t for t in all_themes if t.theme_key != "other"][:10]

    bullish_themes = [t for t in all_themes if t.direction == "bullish"]
    bearish_themes = [t for t in all_themes if t.direction == "bearish"]
    neutral_themes = [t for t in all_themes if t.direction == "neutral"]

    console.print(
        f"  {len(all_themes)} themes ({len(bullish_themes)} bullish, "
        f"{len(bearish_themes)} bearish, {len(neutral_themes)} neutral)"
    )

    # 2. Split + fanout ───────────────────────────────────────────────
    bullish_per_theme = find_all_candidates(bullish_themes, as_of=feature_date, per_theme=8)
    bullish_merged = merge_candidates(bullish_per_theme)

    bearish_per_theme = find_all_candidates(bearish_themes, as_of=feature_date, per_theme=5)
    bearish_merged = merge_candidates(bearish_per_theme)

    console.print(
        f"  Bullish candidates: {len(bullish_merged)}  |  "
        f"Bearish candidates: {len(bearish_merged)}"
    )

    theme_lookup = {t.theme_key: t for t in all_themes}

    # 3. Claude deep reasoning — BULLISH ONLY ─────────────────────────
    reasoner = StockReasoner()
    bullish_to_reason = bullish_merged[: args.max_claude_candidates]
    reasonings: dict[int, StockReasoning] = {}
    total_claude_cost = Decimal("0")

    # Pre-filter: drop candidates with bearish news veto or rally+vol trap
    # (avoid spending Claude tokens on picks that will be rejected anyway)
    from src.ml.xgboost_predictor import _has_trap_flag
    prefilter_vetoed: list[dict] = []
    filtered_to_reason = []
    for cand in bullish_to_reason:
        trapped, reason = _has_trap_flag(cand.stock_id, target_date)
        if trapped:
            prefilter_vetoed.append({"symbol": cand.symbol, "reason": reason})
            continue
        filtered_to_reason.append(cand)

    if prefilter_vetoed:
        console.print(
            f"[yellow]  Pre-filter vetoed {len(prefilter_vetoed)} candidates:[/yellow]"
        )
        for v in prefilter_vetoed:
            console.print(f"    [dim]- {v['symbol']}: {v['reason']}[/dim]")

    bullish_to_reason = filtered_to_reason

    if bullish_to_reason:
        console.print(
            f"\n[cyan]▶ Claude reasoning on {len(bullish_to_reason)} bullish candidates[/cyan]"
        )
        for i, cand in enumerate(bullish_to_reason, 1):
            theme = theme_lookup.get(cand.theme_key)
            if theme is None:
                continue
            console.print(f"  [dim]{i}/{len(bullish_to_reason)}[/dim] {cand.symbol} ({cand.theme_key})")
            r = reasoner.reason(cand, theme, target_date)
            if r:
                reasonings[cand.stock_id] = r
                total_claude_cost += r.cost_inr
        console.print(
            f"  [green]✓[/green] {len(reasonings)} reasonings (cost ₹{total_claude_cost:.3f})"
        )
    else:
        console.print(
            "[yellow]  No bullish candidates from themes — will use XGBoost fallback[/yellow]"
        )

    # 4. Rank bullish picks ───────────────────────────────────────────
    news_picks: list[dict] = []
    for cand in bullish_to_reason:
        r = reasonings.get(cand.stock_id)
        if r is None:
            continue
        # Only keep BUY or HOLD (exclude AVOID even if somehow bullish-theme)
        if r.recommendation == "AVOID":
            continue
        rec_weight = {"BUY": 1.2, "HOLD": 0.8}.get(r.recommendation, 0.8)
        combined = cand.final_score * (r.conviction / 10.0) * rec_weight
        news_picks.append({
            "stock_id": cand.stock_id,
            "symbol": cand.symbol,
            "name": cand.name,
            "sector": cand.sector,
            "last_close": cand.last_close,
            "source": "news_driven",
            "driving_theme": cand.theme_key,
            "theme_direction": cand.theme_direction,
            "conviction": r.conviction,
            "recommendation": r.recommendation,
            "primary_reasoning": r.primary_reasoning,
            "supporting_factors": r.supporting_factors,
            "key_risks": r.key_risks,
            "alternative_scenario": r.alternative_scenario,
            "final_score": combined,
        })
    news_picks.sort(key=lambda x: x["final_score"], reverse=True)
    news_picks = news_picks[: args.top_n]

    console.print(
        f"\n[cyan]▶ {len(news_picks)} news-driven BUY picks after filtering[/cyan]"
    )

    # 5. XGBoost fallback if < top_n ─────────────────────────────────
    gap = args.top_n - len(news_picks)
    xgb_picks: list[dict] = []
    if gap > 0:
        console.print(
            f"[cyan]▶ Need {gap} more picks → supplementing from XGBoost (v3)[/cyan]"
        )
        exclude_ids = {p["stock_id"] for p in news_picks}
        supplement = xgboost_top_buys(
            feature_date=feature_date, exclude_stock_ids=exclude_ids, n=gap
        )
        for s_pick in supplement:
            xgb_picks.append({
                "stock_id": s_pick.stock_id,
                "symbol": s_pick.symbol,
                "name": s_pick.name,
                "sector": s_pick.sector,
                "last_close": s_pick.last_close,
                "source": "xgboost_fallback",
                "driving_theme": "technical_momentum",
                "theme_direction": "bullish",
                "conviction": min(10, int(s_pick.prob_up * 10)),
                "recommendation": "HOLD" if s_pick.prob_up < 0.55 else "BUY",
                "primary_reasoning": (
                    f"XGBoost model prob_up={s_pick.prob_up:.3f}. "
                    "Supplementary pick based on technical/market context features "
                    "(no dominant bullish news theme for this stock)."
                ),
                "supporting_factors": [f"XGBoost v3 prob_up: {s_pick.prob_up:.3f}"],
                "key_risks": [
                    "Not driven by a specific news theme",
                    "Technical-only signal — reversal risk if macro deteriorates",
                ],
                "alternative_scenario": "News flow turns and negates positive technical bias.",
                "final_score": s_pick.prob_up,
            })
        console.print(f"  Added {len(xgb_picks)} XGBoost-fallback picks")

    # Combine
    final_picks = news_picks + xgb_picks
    for i, p in enumerate(final_picks, 1):
        p["rank"] = i

    if not final_picks:
        console.print("[red]No picks produced. Check data/model state.[/red]")
        return 1

    # 5b. Range predictions + ATR-based trade levels ────────────────
    console.print(f"\n[cyan]▶ Predicting intraday ranges + ATR trade levels[/cyan]")
    range_bundle = load_active_range_models()
    ranges_by_stock = {}
    if range_bundle is not None:
        pick_stock_ids = [int(p["stock_id"]) for p in final_picks]
        ranges_by_stock = predict_ranges_for_stocks(
            pick_stock_ids, feature_date, bundle=range_bundle
        )
    else:
        console.print(
            "[yellow]  Range models not available — using ATR-only trade levels[/yellow]"
        )

    # For every pick: compute ATR, derive risk-adjusted stop/target,
    # store the TRADE levels in predicted_low/predicted_high (so live_monitor
    # and validator see them). Raw ML range is kept in model_outputs for audit.
    for p in final_picks:
        stock_id = int(p["stock_id"])
        entry = p.get("last_close")
        if not entry:
            continue

        # ML range (may be None if range model unavailable)
        r = ranges_by_stock.get(stock_id)
        ml_low = ml_high = None
        if r:
            ml_low = round(entry * (1 + r["predicted_low_pct"]), 2)
            ml_high = round(entry * (1 + r["predicted_high_pct"]), 2)
            p["ml_predicted_high_pct"] = r["predicted_high_pct"]
            p["ml_predicted_low_pct"] = r["predicted_low_pct"]
            p["ml_predicted_high"] = ml_high
            p["ml_predicted_low"] = ml_low

        # ATR from recent daily candles
        atr = compute_atr(stock_id, feature_date)

        # Derive risk-adjusted trade levels
        lvl = derive_trade_levels(entry, ml_low, ml_high, atr)

        p["atr"] = lvl.atr
        p["stop_loss"] = lvl.stop_loss
        p["target"] = lvl.target
        p["stop_pct"] = lvl.stop_pct
        p["target_pct"] = lvl.target_pct
        p["rr_ratio"] = lvl.rr_ratio
        p["stop_reason"] = lvl.stop_reason
        p["target_reason"] = lvl.target_reason

        # Persist as predicted_low/high so downstream (validator, live_monitor)
        # reads the risk-adjusted levels — these are what we actually trade.
        p["predicted_low"] = lvl.stop_loss
        p["predicted_high"] = lvl.target

    console.print(
        f"  [green]✓[/green] Trade levels set for "
        f"{sum(1 for p in final_picks if p.get('stop_loss'))} picks (ATR-based where available)"
    )

    # 6. Persist + Run record ─────────────────────────────────────────
    with get_session() as s:
        run = Run(
            run_type=RunType.PREDICTION,
            run_date=target_date,
            started_at=datetime.utcnow(),
            status=RunStatus.RUNNING,
            metadata_json={
                "approach": "news_driven_v1_with_xgb_fallback",
                "target_date": str(target_date),
                "feature_date": str(feature_date),
                "themes_total": len(all_themes),
                "bullish_themes": len(bullish_themes),
                "bearish_themes": len(bearish_themes),
                "news_driven_picks": len(news_picks),
                "xgb_fallback_picks": len(xgb_picks),
            },
        )
        s.add(run)
        s.flush()
        run_id = run.id

    pred_rows = []
    for p in final_picks:
        pred_rows.append({
            "run_id": run_id,
            "run_date": target_date,
            "stock_id": int(p["stock_id"]),
            "direction": "UP",
            "confidence": round(p["conviction"] / 10.0, 3),
            "predicted_low": p.get("predicted_low"),
            "predicted_high": p.get("predicted_high"),
            "buy_rank": int(p["rank"]),
            "model_version": f"news_driven_v1+{p['source']}",
            "reasoning": p["primary_reasoning"][:2000],
            "model_outputs": {
                "source": p["source"],
                "theme_key": p["driving_theme"],
                "theme_direction": p["theme_direction"],
                "conviction": p["conviction"],
                "recommendation": p["recommendation"],
                "final_score": round(float(p["final_score"]), 4),
                "ml_predicted_high_pct": p.get("ml_predicted_high_pct"),
                "ml_predicted_low_pct": p.get("ml_predicted_low_pct"),
                "ml_predicted_high": p.get("ml_predicted_high"),
                "ml_predicted_low": p.get("ml_predicted_low"),
                "atr": p.get("atr"),
                "stop_pct": p.get("stop_pct"),
                "target_pct": p.get("target_pct"),
                "rr_ratio": p.get("rr_ratio"),
                "stop_reason": p.get("stop_reason"),
                "target_reason": p.get("target_reason"),
                "supporting_factors": p["supporting_factors"][:6],
                "key_risks": p["key_risks"][:6],
            },
        })

    stmt = mysql_insert(Prediction).values(pred_rows)
    stmt = stmt.on_duplicate_key_update(
        run_id=stmt.inserted.run_id,
        direction=stmt.inserted.direction,
        confidence=stmt.inserted.confidence,
        predicted_low=stmt.inserted.predicted_low,
        predicted_high=stmt.inserted.predicted_high,
        buy_rank=stmt.inserted.buy_rank,
        model_version=stmt.inserted.model_version,
        reasoning=stmt.inserted.reasoning,
        model_outputs=stmt.inserted.model_outputs,
    )
    with get_session() as s:
        s.execute(stmt)

    # Also clear buy_rank on predictions for this date not in our top_n
    # (so stale picks from earlier runs don't clutter)
    final_stock_ids = {p["stock_id"] for p in final_picks}
    with get_session() as s:
        stale = s.scalars(
            select(Prediction.id)
            .where(Prediction.run_date == target_date)
            .where(Prediction.buy_rank.isnot(None))
            .where(~Prediction.stock_id.in_(final_stock_ids))
        ).all()
        if stale:
            from sqlalchemy import update
            s.execute(
                update(Prediction).where(Prediction.id.in_(stale)).values(buy_rank=None)
            )

    # Finalize run
    with get_session() as s:
        run = s.get(Run, run_id)
        run.completed_at = datetime.utcnow()
        run.status = RunStatus.SUCCESS
        run.duration_sec = int((run.completed_at - run.started_at).total_seconds())
        run.predictions_count = len(pred_rows)
        run.llm_calls_claude = len(reasonings)
        run.total_cost_inr = total_claude_cost

    # 7. Display ──────────────────────────────────────────────────────
    # Themes summary
    if all_themes:
        tt = Table(title="Overnight themes")
        tt.add_column("Theme", style="cyan")
        tt.add_column("Dir", style="magenta")
        tt.add_column("Strength", justify="right", style="green")
        tt.add_column("#Articles", justify="right")
        tt.add_column("#Sources", justify="right")
        for t in all_themes[:8]:
            tt.add_row(
                t.theme_key, t.direction, f"{t.strength:.3f}",
                str(t.article_count), str(t.source_count),
            )
        console.print(tt)

    # Final picks — clean trade setup table (just the math)
    picks_table = Table(
        title=f"{len(final_picks)} Trade Setups for {target_date} ({target_date.strftime('%A')})",
        title_style="bold green",
    )
    picks_table.add_column("#", style="dim")
    picks_table.add_column("Symbol", style="cyan bold")
    picks_table.add_column("Buy at", justify="right")
    picks_table.add_column("Target", justify="right", style="green")
    picks_table.add_column("Stop-loss", justify="right", style="red")
    picks_table.add_column("Upside", justify="right", style="green")
    picks_table.add_column("Downside", justify="right", style="red")
    picks_table.add_column("R:R", justify="right", style="bold yellow")
    picks_table.add_column("ATR", justify="right", style="dim")

    for p in final_picks:
        entry = p.get("last_close")
        target = p.get("target") or p.get("predicted_high")
        stop = p.get("stop_loss") or p.get("predicted_low")
        atr = p.get("atr")

        if entry and target and stop and entry > 0:
            upside_pct = (target - entry) / entry * 100
            downside_pct = (entry - stop) / entry * 100
            rr_ratio = upside_pct / downside_pct if downside_pct > 0 else 0
            entry_str = f"₹{entry:,.2f}"
            target_str = f"₹{target:,.2f}"
            stop_str = f"₹{stop:,.2f}"
            up_str = f"+{upside_pct:.2f}%"
            dn_str = f"-{downside_pct:.2f}%"
            rr_str = f"{rr_ratio:.2f}" if rr_ratio else "—"
            atr_str = f"{atr:.1f}" if atr else "—"
        else:
            entry_str = target_str = stop_str = up_str = dn_str = rr_str = atr_str = "—"

        picks_table.add_row(
            str(p["rank"]), p["symbol"],
            entry_str, target_str, stop_str,
            up_str, dn_str, rr_str, atr_str,
        )
    console.print(picks_table)

    # Bearish watchlist (bonus informational)
    if bearish_merged:
        bear_info = Table(title="[yellow]Bearish watchlist (themes to avoid)[/yellow]")
        bear_info.add_column("Symbol", style="cyan")
        bear_info.add_column("Sector", style="magenta")
        bear_info.add_column("Theme", style="red")
        for c in bearish_merged[:5]:
            bear_info.add_row(c.symbol, c.sector[:15], c.theme_key)
        console.print(bear_info)

    # 8. Markdown report ──────────────────────────────────────────────
    themes_df = pd.DataFrame([{
        "theme_key": t.theme_key, "direction": t.direction,
        "strength": t.strength, "article_count": t.article_count,
        "source_count": t.source_count,
    } for t in all_themes])
    picks_df = pd.DataFrame(final_picks)
    report_path = write_markdown_report(
        report_dir=config.REPORTS_DIR,
        target_date=target_date,
        feature_date=feature_date,
        themes_df=themes_df,
        picks_df=picks_df,
        total_cost_inr=float(total_claude_cost),
        llm_models={
            "bulk": config.LLM_BULK_MODEL,
            "reasoning": config.LLM_REASONING_MODEL,
        },
    )
    console.print(f"\n[green]✓ Report saved: {report_path}[/green]")
    console.print(
        f"[green]✓ Persisted {len(pred_rows)} predictions (run #{run_id})[/green]"
    )
    console.print(
        f"  Sources: {len(news_picks)} news-driven + {len(xgb_picks)} XGBoost fallback"
    )
    console.print(f"  Total Claude cost this run: ₹{total_claude_cost:.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
