"""Main ingestion pipeline — orchestrates all stages in one run.

Daily pre-market flow:
  1. market_data      → incremental OHLCV for Nifty 50
  2. global_indices   → S&P, Nasdaq, Nikkei, etc.
  3. macro_data       → FRED indicators (VIX, DXY, rates, crude)
  4. news             → RSS + NSE announcements + Finnhub
  5. events           → NSE event calendar (earnings, dividends)

Each stage is isolated — failure in one doesn't abort the others. A single
`runs` row records the outcome with per-stage stats in the metadata JSON.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime, timedelta

from sqlalchemy import select

from ..common.logger import get_logger
from ..db.models import Run, RunStatus, RunType, Stock
from ..db.session import get_session
from .events.earnings import ingest_events
from .market.fred_client import backfill_all as fred_backfill
from .market.global_indices import GLOBAL_INDICES, fetch_and_store_index
from .market.yfinance_client import fetch_and_store_for_stock
from .news.aggregator import ingest_all as ingest_news_all

logger = get_logger(__name__)


class IngestionPipeline:
    """Runs all ingestion stages and tracks per-stage stats."""

    def __init__(self, run_type: RunType = RunType.PREDICTION):
        self.run_type = run_type
        self.run_id: int | None = None
        self.stats: dict = {"stages": {}, "errors": []}

    # ─── run lifecycle ────────────────────────────────────────────────

    def start(self, label: str = "daily_ingestion") -> int:
        with get_session() as s:
            run = Run(
                run_type=self.run_type,
                run_date=date.today(),
                started_at=datetime.utcnow(),
                status=RunStatus.RUNNING,
                metadata_json={"pipeline": label},
            )
            s.add(run)
            s.flush()
            self.run_id = run.id
        logger.info("pipeline_started", run_id=self.run_id, label=label)
        return self.run_id

    def finalize(self) -> None:
        with get_session() as s:
            run = s.get(Run, self.run_id)
            if not run:
                return

            run.completed_at = datetime.utcnow()
            run.duration_sec = int(
                (run.completed_at - run.started_at).total_seconds()
            )
            news_stats = self.stats["stages"].get("news", {})
            md_stats = self.stats["stages"].get("market_data", {})
            run.articles_fetched = news_stats.get("articles_fetched", 0) or 0
            run.articles_processed = news_stats.get("articles_persisted", 0) or 0
            run.stocks_processed = md_stats.get("stocks", 0) or 0
            run.error_log = "\n".join(self.stats["errors"]) or None
            run.metadata_json = {
                **(run.metadata_json or {}),
                "stages": self.stats["stages"],
            }

            if self.stats["errors"]:
                all_failed = all(s.get("status") == "failed" for s in self.stats["stages"].values())
                run.status = RunStatus.FAILED if all_failed else RunStatus.PARTIAL
            else:
                run.status = RunStatus.SUCCESS

        logger.info(
            "pipeline_finalized",
            run_id=self.run_id,
            errors=len(self.stats["errors"]),
        )

    # ─── stage runner ─────────────────────────────────────────────────

    def _run_stage(self, name: str, fn: Callable[[], dict]) -> dict:
        start_t = time.time()
        try:
            result = fn() or {}
            duration = time.time() - start_t
            self.stats["stages"][name] = {
                **result,
                "status": "ok",
                "duration_sec": round(duration, 1),
            }
            logger.info(f"stage_ok", stage=name, duration=f"{duration:.1f}s")
            return result
        except Exception as e:
            duration = time.time() - start_t
            err = f"{type(e).__name__}: {e}"
            self.stats["stages"][name] = {
                "status": "failed",
                "error": err,
                "duration_sec": round(duration, 1),
            }
            self.stats["errors"].append(f"{name}: {err}")
            logger.error(f"stage_failed", stage=name, error=err)
            return {"error": err}

    # ─── individual stages ────────────────────────────────────────────

    def ingest_market_data(self, days: int = 5) -> dict:
        end = date.today()
        start = end - timedelta(days=days)

        with get_session() as s:
            stocks = s.scalars(
                select(Stock).where(Stock.currently_active.is_(True))
            ).all()
            for x in stocks:
                s.expunge(x)

        rows_upserted = 0
        failures: list[str] = []
        for stock in stocks:
            result = fetch_and_store_for_stock(stock, start, end, sleep_sec=0.2)
            if result.ok:
                rows_upserted += result.rows_upserted
            else:
                failures.append(stock.symbol)

        return {
            "stocks": len(stocks),
            "rows_upserted": rows_upserted,
            "failures": len(failures),
            "failed_symbols": failures[:10],
        }

    def ingest_global_indices(self, days: int = 5) -> dict:
        end = date.today()
        start = end - timedelta(days=days)
        rows = 0
        failures = []
        for spec in GLOBAL_INDICES:
            result = fetch_and_store_index(spec, start, end, sleep_sec=0.2)
            if result.get("error"):
                failures.append(spec.symbol)
            else:
                rows += result.get("rows", 0)
        return {
            "indices": len(GLOBAL_INDICES),
            "rows_upserted": rows,
            "failures": len(failures),
        }

    def ingest_macro(self, days: int = 15) -> dict:
        end = date.today()
        start = end - timedelta(days=days)
        results = fred_backfill(start, end, sleep_sec=0.1)
        rows = sum(r.get("rows", 0) for r in results if "rows" in r)
        failures = [r for r in results if r.get("error")]
        return {
            "indicators": len(results),
            "rows_upserted": rows,
            "failures": len(failures),
        }

    def ingest_news(self) -> dict:
        return ingest_news_all(sources=["rss", "nse", "finnhub"])

    def ingest_events(self) -> dict:
        return ingest_events()

    # ─── orchestrator ─────────────────────────────────────────────────

    def run_all(self, days: int = 5, label: str = "daily_ingestion") -> dict:
        self.start(label=label)
        try:
            self._run_stage("market_data", lambda: self.ingest_market_data(days))
            self._run_stage("global_indices", lambda: self.ingest_global_indices(days))
            self._run_stage("macro", lambda: self.ingest_macro(15))
            self._run_stage("news", self.ingest_news)
            self._run_stage("events", self.ingest_events)
        finally:
            self.finalize()
        return self.stats
