"""Fetch macro economic indicators from FRED (St. Louis Fed).

FRED is free, generous rate limits, unlimited backfill. Indicators relevant
to Indian markets:
  - VIX (risk/fear gauge — strongly correlated with Nifty drawdowns)
  - DXY / DTWEXBGS (dollar index — affects FII flows to India)
  - 10Y Treasury yield (global risk-free rate)
  - Crude oil (India imports 80%+ of oil — affects IT, energy, aviation)
  - Fed funds rate (global liquidity)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
from fredapi import Fred
from sqlalchemy.dialects.mysql import insert as mysql_insert

from ...common.config import FRED_API_KEY
from ...common.logger import get_logger
from ...db.models import MacroDataDaily
from ...db.session import get_session
from .utils import safe_decimal

logger = get_logger(__name__)


@dataclass
class MacroSpec:
    code: str           # FRED series ID
    name: str           # human-readable
    category: str       # 'volatility' | 'rates' | 'fx' | 'commodity' | 'macro'
    unit: str = ""


# Curated list of macro indicators with known Nifty relevance
MACRO_INDICATORS: list[MacroSpec] = [
    # Volatility
    MacroSpec("VIXCLS", "CBOE VIX (S&P 500 volatility)", "volatility", "index"),

    # Rates
    MacroSpec("DGS10", "US 10-Year Treasury Yield", "rates", "percent"),
    MacroSpec("DGS2", "US 2-Year Treasury Yield", "rates", "percent"),
    MacroSpec("T10Y2Y", "10Y-2Y Spread (yield curve)", "rates", "percent"),
    MacroSpec("FEDFUNDS", "Effective Federal Funds Rate", "rates", "percent"),

    # FX
    MacroSpec("DTWEXBGS", "US Dollar Index (Broad, Goods & Services)", "fx", "index"),
    MacroSpec("DEXINUS", "India/US FX Rate (INR per USD)", "fx", "rupee_per_dollar"),

    # Commodities
    MacroSpec("DCOILWTICO", "WTI Crude Oil (spot price)", "commodity", "usd_per_barrel"),
    MacroSpec("DCOILBRENTEU", "Brent Crude Oil (spot price)", "commodity", "usd_per_barrel"),
    MacroSpec("GOLDAMGBD228NLBM", "Gold Price (London AM Fix)", "commodity", "usd_per_troy_oz"),

    # Macro economic
    MacroSpec("CPIAUCSL", "US CPI (All Urban Consumers)", "macro", "index_1982_84=100"),
    MacroSpec("UNRATE", "US Unemployment Rate", "macro", "percent"),
]


def _fetch_series(fred: Fred, code: str, start: date, end: date) -> pd.Series | None:
    """Fetch a single FRED series, returns pandas Series indexed by date."""
    try:
        series = fred.get_series(
            code, observation_start=start.isoformat(), observation_end=end.isoformat()
        )
        if series is None or len(series) == 0:
            return None
        return series.dropna()
    except Exception as e:
        logger.warning("fred_series_failed", code=code, error=str(e))
        return None


def fetch_and_store_indicator(
    fred: Fred, spec: MacroSpec, start: date, end: date, sleep_sec: float = 0.1
) -> dict:
    """Fetch one FRED series and upsert to macro_data_daily."""
    series = _fetch_series(fred, spec.code, start, end)
    time.sleep(sleep_sec)
    if series is None:
        return {"code": spec.code, "rows": 0, "error": "no_data"}

    rows = []
    for idx, value in series.items():
        try:
            obs_date = idx.date() if hasattr(idx, "date") else idx
        except Exception:
            continue
        rows.append(
            {
                "indicator_code": spec.code,
                "indicator_name": spec.name,
                "category": spec.category,
                "observation_date": obs_date,
                "value": safe_decimal(value, places=6),
                "unit": spec.unit or None,
                "source": "fred",
            }
        )

    if not rows:
        return {"code": spec.code, "rows": 0}

    stmt = mysql_insert(MacroDataDaily).values(rows)
    stmt = stmt.on_duplicate_key_update(
        value=stmt.inserted.value,
        indicator_name=stmt.inserted.indicator_name,
        category=stmt.inserted.category,
        unit=stmt.inserted.unit,
    )
    with get_session() as s:
        s.execute(stmt)

    return {"code": spec.code, "name": spec.name, "rows": len(rows)}


def backfill_all(start: date, end: date, sleep_sec: float = 0.1) -> list[dict]:
    if not FRED_API_KEY:
        logger.error("fred_no_api_key")
        return [{"error": "FRED_API_KEY not set"}]

    fred = Fred(api_key=FRED_API_KEY)
    results = []
    for spec in MACRO_INDICATORS:
        result = fetch_and_store_indicator(fred, spec, start, end, sleep_sec)
        if result.get("error"):
            logger.warning("fred_failed", code=spec.code, error=result["error"])
        else:
            logger.info("fred_ok", code=spec.code, rows=result["rows"])
        results.append(result)
    return results
