"""Post-market validation + WhatsApp summary (triggered at 4:00 PM IST).

Sequence:
  1. Refresh today's OHLCV (market just closed)
  2. Run validate_today.py subprocess (persists validations)
  3. Load today's trade outcomes from DB
  4. Simulate trade P&L per pick
  5. Send EOD summary via WhatsApp

Also computes rolling 7-day P&L + accuracy for context.
"""
from __future__ import annotations

import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import func, select

from src.common.logger import get_logger, setup_logging
from src.db.models import Prediction, Stock, Validation
from src.db.session import get_session
from src.notifications import templates, whatsapp

setup_logging()
logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


def _run_subprocess(script: str, args: list[str] = None) -> tuple[bool, str]:
    args = args or []
    cmd = [str(PYTHON), str(PROJECT_ROOT / script)] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), timeout=600,
        )
        if result.returncode != 0:
            return False, f"exit {result.returncode}: {result.stderr[-500:]}"
        return True, result.stdout[-500:]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _simulate_pnl(entry: float, act_h: float, act_l: float, act_c: float,
                  target: float, stop: float) -> tuple[str, float]:
    if entry <= stop:
        return "SKIP_GAP_DOWN", 0.0
    if entry >= target:
        return "SKIP_GAP_UP", 0.0
    stop_hit = act_l <= stop
    target_hit = act_h >= target
    if stop_hit and target_hit:
        return "AMBIGUOUS_STOP_FIRST", (stop - entry) / entry * 100
    if stop_hit:
        return "STOP", (stop - entry) / entry * 100
    if target_hit:
        return "TARGET", (target - entry) / entry * 100
    return "HOLD", (act_c - entry) / entry * 100


def _compute_eod(target_date: date) -> dict:
    """Return metrics + per-trade list for today's validated picks."""
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
                Validation.direction_correct,
            )
            .join(Prediction, Prediction.id == Validation.prediction_id)
            .join(Stock, Stock.id == Validation.stock_id)
            .where(Validation.run_date == target_date)
            .where(Prediction.buy_rank.isnot(None))
            .order_by(Prediction.buy_rank)
        ).all()

    if not rows:
        return {"total_trades": 0, "trades": []}

    trades = []
    direction_correct = 0
    targets = stops = holds = skipped = 0
    total_pnl = 0.0

    for r in rows:
        if not (r.actual_open and r.actual_high and r.actual_low and r.actual_close
                and r.predicted_low and r.predicted_high):
            continue
        entry = float(r.actual_open)
        outcome, pnl = _simulate_pnl(
            entry,
            float(r.actual_high), float(r.actual_low), float(r.actual_close),
            float(r.predicted_high), float(r.predicted_low),
        )
        trades.append({
            "symbol": r.symbol, "rank": r.buy_rank,
            "outcome": outcome, "pnl_pct": round(pnl, 3),
            "direction_correct": bool(r.direction_correct),
        })
        total_pnl += pnl
        if r.direction_correct:
            direction_correct += 1
        if outcome == "TARGET":
            targets += 1
        elif outcome == "STOP" or "STOP" in outcome:
            stops += 1
        elif "SKIP" in outcome:
            skipped += 1
        else:
            holds += 1

    # 7-day rolling
    cutoff = target_date - timedelta(days=10)  # ~7 trading days
    with get_session() as s:
        roll_rows = s.execute(
            select(
                Validation.actual_open, Validation.actual_high, Validation.actual_low,
                Validation.actual_close, Validation.direction_correct,
                Prediction.predicted_low, Prediction.predicted_high,
            )
            .join(Prediction, Prediction.id == Validation.prediction_id)
            .where(Validation.run_date >= cutoff)
            .where(Validation.run_date <= target_date)
            .where(Prediction.buy_rank.isnot(None))
        ).all()

    roll_pnl = 0.0
    roll_n = 0
    roll_correct = 0
    for rr in roll_rows:
        if not (rr.actual_open and rr.actual_high and rr.actual_low and rr.actual_close
                and rr.predicted_low and rr.predicted_high):
            continue
        _, pnl = _simulate_pnl(
            float(rr.actual_open), float(rr.actual_high), float(rr.actual_low),
            float(rr.actual_close), float(rr.predicted_high), float(rr.predicted_low),
        )
        roll_pnl += pnl
        roll_n += 1
        if rr.direction_correct:
            roll_correct += 1

    return {
        "total_trades": len(trades),
        "direction_correct": direction_correct,
        "target_hits": targets,
        "stop_hits": stops,
        "holds": holds,
        "skipped": skipped,
        "total_pnl_pct": round(total_pnl, 3),
        "rolling_7d_pnl_pct": round(roll_pnl, 3) if roll_n > 0 else None,
        "rolling_7d_accuracy": round(roll_correct / roll_n, 3) if roll_n > 0 else None,
        "trades": trades,
    }


def main() -> int:
    today = datetime.now().date()
    if today.weekday() >= 5:
        logger.info("eod_skip_weekend", weekday=today.weekday())
        return 0

    logger.info("eod_run_start", target_date=str(today))

    # 1. Refresh today's OHLCV
    ok, msg = _run_subprocess("scripts/backfill_market_data.py", ["--days", "2"])
    if not ok:
        logger.warning("market_data_refresh_failed", msg=msg)

    # 2. Validate
    ok, msg = _run_subprocess("scripts/validate_today.py", ["--date", str(today)])
    if not ok:
        logger.error("validation_run_failed", msg=msg)
        whatsapp.send(templates.pipeline_failed("validation", msg))
        return 1

    # 3. Compute metrics
    metrics = _compute_eod(today)
    if metrics["total_trades"] == 0:
        whatsapp.send(
            f"📊 *EOD — {today.strftime('%d %b')}*\n\n"
            f"No validated trades (market data not available yet?). "
            f"Check logs."
        )
        return 1

    # 4. Send summary
    message = templates.eod_summary(today, metrics, metrics["trades"])
    if whatsapp.send(message):
        logger.info("eod_whatsapp_sent", trades=metrics["total_trades"])
        return 0
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("eod_run_fatal", error=str(e))
        whatsapp.send(templates.pipeline_failed("eod_run (fatal)", tb[-500:]))
        sys.exit(1)
