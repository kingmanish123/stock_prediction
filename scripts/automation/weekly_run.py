"""Weekly backtest + report (triggered Sunday 9:00 PM IST).

Computes Monday→Saturday stats from validations in DB, records an algo
experiment row, sends a weekly summary via WhatsApp.

Also surfaces simple insights:
  - best / worst performing stocks
  - best / worst sectors
  - common stop-out patterns
"""
from __future__ import annotations

import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import desc, select

from src.common.logger import get_logger, setup_logging
from src.db.models import AlgoExperiment, Prediction, Stock, Validation
from src.db.session import get_session
from src.notifications import templates, whatsapp

setup_logging()
logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


def _run_subprocess(script: str, args: list[str]) -> tuple[bool, str]:
    cmd = [str(PYTHON), str(PROJECT_ROOT / script)] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                cwd=str(PROJECT_ROOT), timeout=600)
        return result.returncode == 0, result.stdout[-500:]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _last_trading_week(today: date) -> tuple[date, date]:
    """Return (monday, saturday) for the week just ending."""
    # If Sunday, last week = Monday to Saturday just past
    weekday = today.weekday()  # Mon=0..Sun=6
    # Days back to last Monday
    days_back_to_monday = weekday + 7 if weekday < 6 else 6
    # Simpler: last Monday before today (or today if Monday)
    if weekday == 6:  # Sunday
        monday = today - timedelta(days=6)
    else:
        monday = today - timedelta(days=weekday + 7)
    saturday = monday + timedelta(days=5)
    return monday, saturday


def _extract_insights(week_start: date, week_end: date) -> list[str]:
    """Mine validations for interesting patterns to include in the WhatsApp report."""
    insights: list[str] = []

    with get_session() as s:
        # Best performer symbol (most target hits)
        rows = s.execute(
            select(
                Stock.symbol,
                Validation.actual_return_pct,
                Prediction.predicted_low,
                Prediction.predicted_high,
                Validation.actual_high,
                Validation.actual_low,
                Validation.actual_open,
            )
            .join(Prediction, Prediction.id == Validation.prediction_id)
            .join(Stock, Stock.id == Validation.stock_id)
            .where(Validation.run_date >= week_start, Validation.run_date <= week_end)
            .where(Prediction.buy_rank.isnot(None))
        ).all()

    if not rows:
        return insights

    # Target-hit count per symbol
    from collections import Counter
    target_by_sym: Counter = Counter()
    for r in rows:
        if not (r.actual_high and r.predicted_high and r.actual_open and r.predicted_low):
            continue
        entry = float(r.actual_open)
        if entry <= float(r.predicted_low):
            continue  # gap-down, didn't trade
        if float(r.actual_high) >= float(r.predicted_high):
            target_by_sym[r.symbol] += 1

    if target_by_sym:
        top = target_by_sym.most_common(3)
        for sym, count in top:
            if count >= 2:
                insights.append(f"{sym} hit target {count} times this week")

    # Average daily P&L per weekday (Monday best? Friday worst?)
    # Skip this for MVP — keep report short.

    return insights


def main() -> int:
    today = datetime.now().date()
    if today.weekday() != 6:
        logger.info("weekly_skip_not_sunday", weekday=today.weekday())

    week_start, week_end = _last_trading_week(today)
    logger.info("weekly_run_start", week_start=str(week_start), week_end=str(week_end))

    # 1. Record backtest experiment
    version = f"auto-{week_end.isoformat()}"
    ok, output = _run_subprocess(
        "scripts/backtest_algo.py",
        [
            "--algo-name", "atr_ta_nifty500",
            "--algo-version", version,
            "--start", str(week_start),
            "--end", str(week_end),
            "--notes", f"Auto-weekly report for {week_start}→{week_end}",
        ],
    )
    if not ok:
        logger.error("weekly_backtest_failed", msg=output)
        whatsapp.send(templates.pipeline_failed("weekly backtest", output))
        return 1

    # 2. Load the recorded experiment
    with get_session() as s:
        exp = s.execute(
            select(AlgoExperiment)
            .where(
                AlgoExperiment.algo_name == "atr_ta_nifty500",
                AlgoExperiment.algo_version == version,
                AlgoExperiment.start_date == week_start,
                AlgoExperiment.end_date == week_end,
            )
        ).scalar_one_or_none()

    if exp is None:
        logger.error("weekly_experiment_not_found", version=version)
        return 1

    metrics = {
        "trading_days_covered": exp.trading_days_covered,
        "total_trades": exp.total_trades,
        "direction_accuracy": exp.direction_accuracy,
        "target_hits": exp.target_hits,
        "stop_hits": exp.stop_hits,
        "total_pnl_pct": exp.total_pnl_pct,
        "avg_pnl_pct": exp.avg_pnl_pct,
        "sharpe_ratio": exp.sharpe_ratio,
    }
    insights = _extract_insights(week_start, week_end)

    # 3. Send WhatsApp
    message = templates.weekly_summary(week_start, week_end, metrics, insights)
    if whatsapp.send(message):
        logger.info("weekly_whatsapp_sent")
        return 0
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("weekly_run_fatal", error=str(e))
        whatsapp.send(templates.pipeline_failed("weekly_run (fatal)", tb[-500:]))
        sys.exit(1)
