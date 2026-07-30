"""Upstox REST API v2 client for market data.

Minimal wrapper around the endpoints we actually use:
  - LTP (last traded price) — for live_check.py
  - Full market quote — includes OHLC + bid/ask depth
  - Historical daily candles — for backtests
  - Intraday candles — for mid-day re-ranking (future use)

Handles auth via bearer token from config / explicit param.
"""
from __future__ import annotations

from typing import Iterable

import httpx

from ..common import config
from ..common.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.upstox.com/v2"
API_VERSION = "2.0"


class UpstoxError(Exception):
    pass


class UpstoxClient:
    """Authenticated HTTP client for Upstox market data."""

    def __init__(self, access_token: str | None = None, timeout: float = 20.0):
        self.access_token = access_token or config.UPSTOX_ACCESS_TOKEN
        if not self.access_token:
            raise UpstoxError(
                "UPSTOX_ACCESS_TOKEN not set. Run `python scripts/upstox_login.py` first."
            )
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={
                "Accept": "application/json",
                "Api-Version": API_VERSION,
                "Authorization": f"Bearer {self.access_token}",
            },
            timeout=timeout,
        )

    def __enter__(self) -> "UpstoxClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ─── helpers ────────────────────────────────────────────────────

    @staticmethod
    def _normalize_instrument_response_key(api_key: str) -> str:
        """Upstox returns keys like 'NSE_EQ:INFOSYS'. Normalize to 'NSE_EQ|<symbol>'."""
        return api_key.replace(":", "|")

    # ─── market quote ───────────────────────────────────────────────

    def get_ltp(self, instrument_keys: Iterable[str]) -> dict[str, float]:
        """Return {instrument_key: last_traded_price}.

        Accepts up to 500 instrument keys per call per Upstox docs.
        """
        keys = list(instrument_keys)
        if not keys:
            return {}
        resp = self._client.get(
            "/market-quote/ltp",
            params={"instrument_key": ",".join(keys)},
        )
        resp.raise_for_status()
        data = resp.json().get("data", {}) or {}

        out: dict[str, float] = {}
        for api_key, info in data.items():
            ik = info.get("instrument_token") or self._normalize_instrument_response_key(api_key)
            price = info.get("last_price")
            if price is not None:
                out[ik] = float(price)
        return out

    def get_full_quote(self, instrument_keys: Iterable[str]) -> dict[str, dict]:
        """Return comprehensive quote data (OHLC, volume, bid/ask depth) per instrument."""
        keys = list(instrument_keys)
        if not keys:
            return {}
        resp = self._client.get(
            "/market-quote/quotes",
            params={"instrument_key": ",".join(keys)},
        )
        resp.raise_for_status()
        return resp.json().get("data", {}) or {}

    # ─── candles ────────────────────────────────────────────────────

    def get_historical_candles(
        self,
        instrument_key: str,
        interval: str,
        to_date: str,
        from_date: str,
    ) -> list[list]:
        """Historical candles (interval = 'day'|'week'|'month').

        Returns list of [timestamp, open, high, low, close, volume, oi] rows.
        """
        url = f"/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("candles", []) or []

    def get_intraday_candles(
        self,
        instrument_key: str,
        interval: str = "1minute",
    ) -> list[list]:
        """Today's intraday candles.

        Intervals: '1minute', '30minute' (check Upstox docs for latest options).
        """
        url = f"/historical-candle/intraday/{instrument_key}/{interval}"
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("candles", []) or []

    # ─── user / profile sanity check ────────────────────────────────

    def ping(self) -> dict:
        """Fetch user profile — cheap way to validate the access token."""
        resp = self._client.get("/user/profile")
        resp.raise_for_status()
        return resp.json().get("data", {}) or {}
