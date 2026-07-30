"""Post-market validation — compare predictions to actual OHLCV.

Flow:
  1. Find predictions where run_date has actual OHLCV and no validation yet
  2. Compute direction_correct + return + range_hit
  3. Persist to validations table
  4. Update daily_metrics table with rolling aggregates
  5. Print summary table

Usage:
    python scripts/validate_today.py                       # validate all unvalidated
    python scripts/validate_today.py --date 2026-04-22     # specific date only
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import and_, case, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from src.common.logger import setup_logging
from src.db.models import (
    DailyMetric,
    MarketDataDaily,
    Prediction,
    Stock,
    Validation,
)
from src.db.session import get_session

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--date",
        type=str,
        help="Validate only this target date (YYYY-MM-DD). Default: all unvalidated.",
    )
    return p.parse_args()


def _find_validation_candidates(target_date_filter: date | None):
    """Fetch predictions with actuals but no validation row yet."""
    with get_session() as s:
        stmt = (
            select(
                Prediction.id.label("prediction_id"),
                Prediction.run_date,
                Prediction.stock_id,
                Stock.symbol,
                Prediction.direction,
                Prediction.confidence,
                Prediction.buy_rank,
                Prediction.sell_rank,
                Prediction.predicted_low,
                Prediction.predicted_high,
                MarketDataDaily.open,
                MarketDataDaily.high,
                MarketDataDaily.low,
                MarketDataDaily.close,
                MarketDataDaily.volume,
            )
            .join(Stock, Stock.id == Prediction.stock_id)
            .outerjoin(Validation, Validation.prediction_id == Prediction.id)
            .join(
                MarketDataDaily,
                and_(
                    MarketDataDaily.stock_id == Prediction.stock_id,
                    MarketDataDaily.trade_date == Prediction.run_date,
                ),
            )
            .where(Validation.id.is_(None))
            .where(Prediction.run_date <= date.today())
        )
        if target_date_filter:
            stmt = stmt.where(Prediction.run_date == target_date_filter)
        return s.execute(stmt).all()


def _compute_validation_row(pred_row) -> dict | None:
    open_p = float(pred_row.open) if pred_row.open else None
    close_p = float(pred_row.close) if pred_row.close else None
    high_p = float(pred_row.high) if pred_row.high else None
    low_p = float(pred_row.low) if pred_row.low else None

    if open_p is None or close_p is None or open_p == 0:
        return None

    actual_return = (close_p - open_p) / open_p
    predicted_up = pred_row.direction == "UP"
    actually_up = actual_return > 0
    direction_correct = predicted_up == actually_up

    # With new ATR-based trade levels, predicted_low = stop, predicted_high = target.
    # "range_hit" now means: did price travel inside the tradeable range?
    # For P&L, we separately track target_hit / stop_hit via actual_high/low.
    range_hit = None
    range_overlap = None
    if pred_row.predicted_low is not None and pred_row.predicted_high is not None:
        plo = float(pred_row.predicted_low)
        phi = float(pred_row.predicted_high)
        if high_p is not None and low_p is not None:
            overlap_lo = max(plo, low_p)
            overlap_hi = min(phi, high_p)
            overlap = max(0, overlap_hi - overlap_lo)
            actual_range = high_p - low_p
            range_overlap = overlap / actual_range if actual_range > 0 else 0.0
            range_hit = overlap > 0

    return {
        "prediction_id": pred_row.prediction_id,
        "run_date": pred_row.run_date,
        "stock_id": pred_row.stock_id,
        "actual_open": open_p,
        "actual_high": high_p,
        "actual_low": low_p,
        "actual_close": close_p,
        "actual_volume": int(pred_row.volume) if pred_row.volume else None,
        "actual_return_pct": round(actual_return * 100, 4),
        "direction_correct": direction_correct,
        "range_hit": range_hit,
        "range_overlap_pct": round(range_overlap, 3) if range_overlap is not None else None,
    }


def _simulate_trade_pnl(
    entry: float,
    actual_open: float,
    actual_high: float,
    actual_low: float,
    actual_close: float,
    target: float,
    stop: float,
) -> dict:
    """Compute realistic intraday P&L given trade levels.

    Entry = actual_open in practice. If open invalidates the setup (gap past
    the stop or target), we DON'T TAKE the trade — P&L = 0.

    Otherwise assume entry at open, check if stop hit before target.
    When both high and low breach their levels, conservatively assume the stop
    triggered first (worst-case — protects against optimistic simulation).
    """
    # Gap-past-levels: setup invalidated, don't enter.
    if actual_open <= stop:
        return {"outcome": "SKIP_GAP_DOWN", "pnl_pct": 0.0}
    if actual_open >= target:
        return {"outcome": "SKIP_GAP_UP", "pnl_pct": 0.0}

    stop_hit = actual_low <= stop
    target_hit = actual_high >= target

    if stop_hit and target_hit:
        # Both hit during day — conservative: assume stop triggered first
        return {"outcome": "AMBIGUOUS_STOP_FIRST", "pnl_pct": (stop - entry) / entry * 100}
    if stop_hit:
        return {"outcome": "STOP", "pnl_pct": (stop - entry) / entry * 100}
    if target_hit:
        return {"outcome": "TARGET", "pnl_pct": (target - entry) / entry * 100}
    # Neither hit — exit at close
    return {"outcome": "HOLD", "pnl_pct": (actual_close - entry) / entry * 100}


def _upsert_validations(val_rows: list[dict]) -> int:
    if not val_rows:
        return 0
    with get_session() as s:
        stmt = mysql_insert(Validation).values(val_rows)
        stmt = stmt.on_duplicate_key_update(
            actual_open=stmt.inserted.actual_open,
            actual_high=stmt.inserted.actual_high,
            actual_low=stmt.inserted.actual_low,
            actual_close=stmt.inserted.actual_close,
            actual_volume=stmt.inserted.actual_volume,
            actual_return_pct=stmt.inserted.actual_return_pct,
            direction_correct=stmt.inserted.direction_correct,
            range_hit=stmt.inserted.range_hit,
            range_overlap_pct=stmt.inserted.range_overlap_pct,
            validated_at=datetime.utcnow(),
        )
        s.execute(stmt)
    return len(val_rows)


def _compute_daily_metrics(target_date: date) -> dict:
    """Compute today's metrics + rolling 30-day."""
    cutoff = target_date - timedelta(days=30)
    with get_session() as s:
        # Today's metrics
        row = s.execute(
            select(
                func.count(Validation.id).label("total"),
                func.sum(case((Validation.direction_correct.is_(True), 1), else_=0)).label("correct"),
            ).where(Validation.run_date == target_date)
        ).first()
        today_total = int(row.total or 0)
        today_correct = int(row.correct or 0)

        # Top-5 BUY performance today
        top5_buy_row = s.execute(
            select(
                func.count(Validation.id).label("total"),
                func.sum(case((Validation.direction_correct.is_(True), 1), else_=0)).label("correct"),
                func.avg(Validation.actual_return_pct).label("avg_return"),
            )
            .join(Prediction, Prediction.id == Validation.prediction_id)
            .where(Prediction.run_date == target_date, Prediction.buy_rank.isnot(None))
        ).first()
        top5_buy_correct = int(top5_buy_row.correct or 0)
        top5_buy_avg_ret = float(top5_buy_row.avg_return or 0)

        top5_sell_row = s.execute(
            select(
                func.count(Validation.id).label("total"),
                func.sum(case((Validation.direction_correct.is_(True), 1), else_=0)).label("correct"),
                func.avg(Validation.actual_return_pct).label("avg_return"),
            )
            .join(Prediction, Prediction.id == Validation.prediction_id)
            .where(Prediction.run_date == target_date, Prediction.sell_rank.isnot(None))
        ).first()
        top5_sell_correct = int(top5_sell_row.correct or 0)
        top5_sell_avg_ret = float(top5_sell_row.avg_return or 0)

        # Rolling 30-day
        roll = s.execute(
            select(
                func.count(Validation.id).label("total"),
                func.sum(case((Validation.direction_correct.is_(True), 1), else_=0)).label("correct"),
            ).where(Validation.run_date >= cutoff, Validation.run_date <= target_date)
        ).first()
        roll_total = int(roll.total or 0)
        roll_correct = int(roll.correct or 0)

        roll_buy = s.execute(
            select(
                func.count(Validation.id).label("total"),
                func.sum(case((Validation.direction_correct.is_(True), 1), else_=0)).label("correct"),
            )
            .join(Prediction, Prediction.id == Validation.prediction_id)
            .where(
                Prediction.run_date >= cutoff,
                Prediction.run_date <= target_date,
                Prediction.buy_rank.isnot(None),
            )
        ).first()
        roll_buy_total = int(roll_buy.total or 0)
        roll_buy_correct = int(roll_buy.correct or 0)

    metrics = {
        "today_direction_accuracy": today_correct / today_total if today_total else None,
        "today_total_predictions": today_total,
        "today_direction_correct": today_correct,
        "top5_buy_correct": top5_buy_correct,
        "top5_buy_avg_return_pct": top5_buy_avg_ret,
        "top5_sell_correct": top5_sell_correct,
        "top5_sell_avg_return_pct": top5_sell_avg_ret,
        "rolling_30d_accuracy": roll_correct / roll_total if roll_total else None,
        "rolling_30d_total": roll_total,
        "rolling_30d_top5_buy_hit_rate": roll_buy_correct / roll_buy_total if roll_buy_total else None,
    }
    return metrics


def _upsert_daily_metrics(target_date: date, metrics: dict) -> None:
    row = {
        "metric_date": target_date,
        "total_predictions": metrics["today_total_predictions"],
        "direction_correct_count": metrics["today_direction_correct"],
        "direction_accuracy": (
            round(metrics["today_direction_accuracy"], 3)
            if metrics["today_direction_accuracy"] is not None else None
        ),
        "top5_buy_correct": metrics["top5_buy_correct"],
        "top5_buy_avg_return_pct": round(metrics["top5_buy_avg_return_pct"], 4) if metrics["top5_buy_avg_return_pct"] is not None else None,
        "top5_sell_correct": metrics["top5_sell_correct"],
        "top5_sell_avg_return_pct": round(metrics["top5_sell_avg_return_pct"], 4) if metrics["top5_sell_avg_return_pct"] is not None else None,
        "rolling_30d_direction_accuracy": (
            round(metrics["rolling_30d_accuracy"], 3)
            if metrics["rolling_30d_accuracy"] is not None else None
        ),
        "rolling_30d_top5_buy_hit_rate": (
            round(metrics["rolling_30d_top5_buy_hit_rate"], 3)
            if metrics["rolling_30d_top5_buy_hit_rate"] is not None else None
        ),
    }
    with get_session() as s:
        stmt = mysql_insert(DailyMetric).values(row)
        stmt = stmt.on_duplicate_key_update(
            total_predictions=stmt.inserted.total_predictions,
            direction_correct_count=stmt.inserted.direction_correct_count,
            direction_accuracy=stmt.inserted.direction_accuracy,
            top5_buy_correct=stmt.inserted.top5_buy_correct,
            top5_buy_avg_return_pct=stmt.inserted.top5_buy_avg_return_pct,
            top5_sell_correct=stmt.inserted.top5_sell_correct,
            top5_sell_avg_return_pct=stmt.inserted.top5_sell_avg_return_pct,
            rolling_30d_direction_accuracy=stmt.inserted.rolling_30d_direction_accuracy,
            rolling_30d_top5_buy_hit_rate=stmt.inserted.rolling_30d_top5_buy_hit_rate,
            computed_at=datetime.utcnow(),
        )
        s.execute(stmt)


def main() -> int:
    args = parse_args()
    target_date_filter = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    )

    console.print(Panel.fit("Post-Market Validation", border_style="cyan"))

    # 1. Find candidates
    candidates = _find_validation_candidates(target_date_filter)

    # Group by date for reporting
    dates_found = sorted({c.run_date for c in candidates})

    # When --date is specified, also include existing validations for that date
    # so we can re-print the report even if nothing new to validate.
    if target_date_filter and target_date_filter not in dates_found:
        with get_session() as s:
            existing_count = s.scalar(
                select(func.count(Validation.id)).where(Validation.run_date == target_date_filter)
            ) or 0
        if existing_count > 0:
            dates_found = [target_date_filter]
            console.print(
                f"  No new predictions to validate; re-rendering metrics for [bold]{target_date_filter}[/bold] "
                f"({existing_count} existing validations)\n"
            )

    if not candidates and not dates_found:
        console.print("[yellow]No unvalidated predictions with actuals available.[/yellow]")
        return 0
    console.print(
        f"  Validating [bold]{len(candidates)}[/bold] predictions "
        f"across [bold]{len(dates_found)}[/bold] dates: {dates_found[0]} → {dates_found[-1]}"
    )

    # 2. Compute + persist
    val_rows = []
    for c in candidates:
        row = _compute_validation_row(c)
        if row:
            val_rows.append(row)
    inserted = _upsert_validations(val_rows)
    console.print(f"  [green]✓ Persisted {inserted} validation rows[/green]\n")

    # 3. Compute + store per-date metrics
    for target_date in dates_found:
        metrics = _compute_daily_metrics(target_date)
        _upsert_daily_metrics(target_date, metrics)

    # 4. Latest date summary
    latest = max(dates_found)
    latest_metrics = _compute_daily_metrics(latest)

    # ranked validation sample
    with get_session() as s:
        sample_rows = s.execute(
            select(
                Stock.symbol,
                Prediction.direction,
                Prediction.confidence,
                Prediction.buy_rank,
                Prediction.sell_rank,
                Validation.actual_return_pct,
                Validation.direction_correct,
            )
            .join(Prediction, Prediction.id == Validation.prediction_id)
            .join(Stock, Stock.id == Validation.stock_id)
            .where(Validation.run_date == latest)
            .where(
                (Prediction.buy_rank.isnot(None)) | (Prediction.sell_rank.isnot(None))
            )
            .order_by(
                # MariaDB: NULLs sort first by default; emulate NULLS LAST
                Prediction.buy_rank.is_(None),
                Prediction.buy_rank,
                Prediction.sell_rank,
            )
        ).all()

    # Today's accuracy panel
    day_acc = latest_metrics["today_direction_accuracy"]
    day_total = latest_metrics["today_total_predictions"]
    summary = Table(title=f"Results for {latest}")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Total predictions", str(day_total))
    summary.add_row("Direction correct", f"{latest_metrics['today_direction_correct']}")
    summary.add_row("Direction accuracy", f"{day_acc:.3f}" if day_acc else "—")
    summary.add_row(
        "Top-5 BUY correct",
        f"{latest_metrics['top5_buy_correct']} / 5 "
        f"(avg return {latest_metrics['top5_buy_avg_return_pct']:+.3f}%)",
    )
    summary.add_row(
        "Top-5 SELL correct",
        f"{latest_metrics['top5_sell_correct']} / 5 "
        f"(avg return {latest_metrics['top5_sell_avg_return_pct']:+.3f}%)",
    )
    roll = latest_metrics["rolling_30d_accuracy"]
    roll_hit = latest_metrics["rolling_30d_top5_buy_hit_rate"]
    summary.add_row("Rolling 30-day accuracy", f"{roll:.3f}" if roll else "—")
    summary.add_row(
        "Rolling 30-day Top-5 BUY hit rate",
        f"{roll_hit:.3f}" if roll_hit else "—",
    )
    summary.add_row("Target accuracy", "0.600")
    summary.add_row("Target Top-5 BUY hit rate", "0.600")
    console.print(summary)

    # Detail table
    if sample_rows:
        detail = Table(title=f"Top-5 BUY / SELL detail — {latest}")
        detail.add_column("Rank", style="dim")
        detail.add_column("Side")
        detail.add_column("Symbol", style="cyan")
        detail.add_column("Predicted")
        detail.add_column("Actual return", justify="right")
        detail.add_column("Correct?")
        for r in sample_rows:
            side = "BUY" if r.buy_rank else "SELL"
            rank_str = f"{r.buy_rank or r.sell_rank}"
            ret_str = f"{r.actual_return_pct:+.3f}%" if r.actual_return_pct is not None else "—"
            ok_str = "[green]✓[/green]" if r.direction_correct else "[red]✗[/red]"
            detail.add_row(
                rank_str, side, r.symbol,
                r.direction,
                ret_str, ok_str,
            )
        console.print(detail)

    # ─── Trade P&L simulation ─────────────────────────────────────
    # For each BUY pick: simulate trade outcome (entry=open, stop/target from predictions)
    _print_trade_pnl_summary(latest)

    return 0


def _print_trade_pnl_summary(target_date: date) -> None:
    """Print realistic P&L summary assuming each BUY pick is traded at open."""
    with get_session() as s:
        rows = s.execute(
            select(
                Stock.symbol,
                Prediction.buy_rank,
                Prediction.predicted_low,
                Prediction.predicted_high,
                Validation.actual_open,
                Validation.actual_high,
                Validation.actual_low,
                Validation.actual_close,
            )
            .join(Prediction, Prediction.id == Validation.prediction_id)
            .join(Stock, Stock.id == Validation.stock_id)
            .where(Validation.run_date == target_date)
            .where(Prediction.buy_rank.isnot(None))
            .order_by(Prediction.buy_rank)
        ).all()

    if not rows:
        return

    pnl_table = Table(
        title=f"Trade P&L simulation — {target_date} "
        f"(entry=open, stop/target from predicted_low/high)",
        title_style="bold cyan",
    )
    pnl_table.add_column("#", style="dim")
    pnl_table.add_column("Symbol", style="cyan")
    pnl_table.add_column("Entry", justify="right")
    pnl_table.add_column("Target", justify="right", style="green")
    pnl_table.add_column("Stop", justify="right", style="red")
    pnl_table.add_column("Act H", justify="right")
    pnl_table.add_column("Act L", justify="right")
    pnl_table.add_column("Outcome")
    pnl_table.add_column("P&L %", justify="right", style="bold")

    total_pnl = 0.0
    target_hits = stop_hits = holds = 0

    for r in rows:
        if not (
            r.predicted_low and r.predicted_high and
            r.actual_open and r.actual_high and r.actual_low and r.actual_close
        ):
            continue
        stop = float(r.predicted_low)
        target = float(r.predicted_high)
        entry = float(r.actual_open)
        act_h = float(r.actual_high)
        act_l = float(r.actual_low)
        act_c = float(r.actual_close)

        sim = _simulate_trade_pnl(entry, entry, act_h, act_l, act_c, target, stop)
        pnl_pct = sim["pnl_pct"]
        outcome = sim["outcome"]
        total_pnl += pnl_pct
        if "TARGET" in outcome:
            target_hits += 1
        elif "STOP" in outcome:
            stop_hits += 1
        else:
            holds += 1

        pnl_color = "green" if pnl_pct > 0 else "red"
        outcome_color = "green" if "TARGET" in outcome else ("red" if "STOP" in outcome else "yellow")
        pnl_table.add_row(
            str(r.buy_rank),
            r.symbol,
            f"₹{entry:,.2f}",
            f"₹{target:,.2f}",
            f"₹{stop:,.2f}",
            f"₹{act_h:,.2f}",
            f"₹{act_l:,.2f}",
            f"[{outcome_color}]{outcome}[/{outcome_color}]",
            f"[{pnl_color}]{pnl_pct:+.2f}%[/{pnl_color}]",
        )

    console.print(pnl_table)

    summary_line = (
        f"[bold]Summary:[/bold] Targets={target_hits}  Stops={stop_hits}  Holds={holds}  |  "
        f"Total P&L = [{'green' if total_pnl >= 0 else 'red'} bold]{total_pnl:+.2f}%[/]  |  "
        f"Avg per trade = [{'green' if total_pnl >= 0 else 'red'} bold]{total_pnl/len(rows):+.3f}%[/]"
    )
    console.print(Panel(summary_line, border_style="cyan"))


if __name__ == "__main__":
    sys.exit(main())
