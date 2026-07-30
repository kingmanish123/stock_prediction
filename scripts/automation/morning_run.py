"""Pre-market morning pipeline (triggered at 7:45 AM via launchd).

Sequence:
  1. Ingest overnight news (NSE/BSE announcements + RSS feeds)
  2. Market data refresh (previous day's close)
  3. Run predict_today.py subprocess → 10 picks persisted
  4. Load today's picks from DB
  5. Send morning picks via WhatsApp

All failures are caught and reported via WhatsApp so we never go silent.
"""
from __future__ import annotations

import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import select

from src.common import config
from src.common.logger import get_logger, setup_logging
from src.db.models import Prediction, Stock
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
            cwd=str(PROJECT_ROOT), timeout=900,
        )
        if result.returncode != 0:
            return False, f"exit {result.returncode}: {result.stderr[-500:]}"
        return True, result.stdout[-500:]
    except subprocess.TimeoutExpired:
        return False, "timed out (>15 min)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _next_trading_day(d: date) -> date:
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def _load_todays_picks(target_date: date) -> list[dict]:
    with get_session() as s:
        rows = s.execute(
            select(
                Prediction.buy_rank,
                Stock.symbol,
                Prediction.predicted_low,
                Prediction.predicted_high,
                Prediction.model_outputs,
            )
            .join(Stock, Stock.id == Prediction.stock_id)
            .where(Prediction.run_date == target_date)
            .where(Prediction.buy_rank.isnot(None))
            .order_by(Prediction.buy_rank)
        ).all()

    picks = []
    for r in rows:
        mo = r.model_outputs or {}
        picks.append({
            "rank": r.buy_rank,
            "symbol": r.symbol,
            # For display we treat predicted_low = stop, predicted_high = target
            "last_close": None,  # will be enriched below
            "stop_loss": float(r.predicted_low) if r.predicted_low else None,
            "target": float(r.predicted_high) if r.predicted_high else None,
            "rr_ratio": mo.get("rr_ratio") or 1.5,
            "conviction": mo.get("conviction"),
            "source": mo.get("source", "unknown"),
        })

    # Enrich last_close from market_data_daily
    from src.db.models import MarketDataDaily
    with get_session() as s:
        for p in picks:
            stock = s.execute(
                select(Stock.id).where(Stock.symbol == p["symbol"])
            ).scalar_one_or_none()
            if not stock:
                continue
            row = s.execute(
                select(MarketDataDaily.close)
                .where(MarketDataDaily.stock_id == stock)
                .where(MarketDataDaily.trade_date < target_date)
                .order_by(MarketDataDaily.trade_date.desc())
                .limit(1)
            ).first()
            if row and row.close:
                p["last_close"] = float(row.close)

    return picks


def main() -> int:
    today = datetime.now().date()
    target_date = _next_trading_day(today - timedelta(days=1)) if today.weekday() < 5 else today

    logger.info("morning_run_start", target_date=str(target_date))

    # 1. News ingestion
    ok, msg = _run_subprocess("scripts/run_ingestion.py")
    if not ok:
        logger.error("news_ingestion_failed", msg=msg)
        whatsapp.send(templates.pipeline_failed("news ingestion", msg))
        # Don't abort — predictions can still run on older news if ingestion partially worked
    logger.info("news_ingestion_done")

    # 2. Market data refresh (last 3 days buffer — cheap safety)
    ok, msg = _run_subprocess(
        "scripts/backfill_market_data.py",
        ["--days", "3"],
    )
    if not ok:
        logger.error("market_data_refresh_failed", msg=msg)
    logger.info("market_data_refresh_done")

    # 3. Run prediction pipeline
    ok, msg = _run_subprocess(
        "scripts/predict_today.py",
        ["--target-date", str(target_date)],
    )
    if not ok:
        logger.error("prediction_run_failed", msg=msg)
        whatsapp.send(templates.pipeline_failed("prediction pipeline", msg))
        return 1
    logger.info("prediction_run_done")

    # 4. Load picks + send WhatsApp
    picks = _load_todays_picks(target_date)
    if not picks:
        whatsapp.send(templates.no_picks_today(target_date, "prediction pipeline produced zero picks"))
        return 1

    message = templates.morning_picks(picks, target_date)
    sent = whatsapp.send(message)
    if sent:
        logger.info("morning_whatsapp_sent", picks_count=len(picks))
    else:
        logger.warning("morning_whatsapp_failed")
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("morning_run_fatal", error=str(e))
        whatsapp.send(templates.pipeline_failed("morning_run (fatal)", tb[-500:]))
        sys.exit(1)
