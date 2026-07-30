"""Fetch corporate events (earnings, board meetings, dividends) from NSE.

NSE publishes upcoming corporate actions at:
  https://www.nseindia.com/api/corporates-meetings?index=equities

This is free, authoritative, and covers all NSE-listed stocks. We filter to our
Nifty 50 universe and categorize into our EventType enum.

Finnhub is NOT used here — its earnings_calendar endpoint for international stocks
requires a premium plan (confirmed 401 on free tier).
"""
from __future__ import annotations

import re
from datetime import date, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from ...common.logger import get_logger
from ...db.models import CorporateEvent, EventStatus, EventType, Stock
from ...db.session import get_session

logger = get_logger(__name__)

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar",
}

NSE_HOME = "https://www.nseindia.com"
NSE_MEETINGS_URL = "https://www.nseindia.com/api/event-calendar?index=equities"


# Classify the NSE purpose string into our EventType enum
_PURPOSE_PATTERNS: list[tuple[re.Pattern, EventType]] = [
    (re.compile(r"quarterly.*result|financial.*result|audited.*result", re.I), EventType.EARNINGS_ANNOUNCEMENT),
    (re.compile(r"dividend", re.I), EventType.DIVIDEND),
    (re.compile(r"bonus", re.I), EventType.BONUS),
    (re.compile(r"split|stock\s*split|sub.?division", re.I), EventType.SPLIT),
    (re.compile(r"rights\s*issue", re.I), EventType.RIGHTS_ISSUE),
    (re.compile(r"buy.?back", re.I), EventType.BUYBACK),
    (re.compile(r"merger|amalgamation", re.I), EventType.MERGER),
    (re.compile(r"acquisition", re.I), EventType.ACQUISITION),
    (re.compile(r"board\s*meet", re.I), EventType.BOARD_MEETING),
    (re.compile(r"rating", re.I), EventType.CREDIT_RATING),
]


def _classify(purpose: str) -> EventType:
    for pat, etype in _PURPOSE_PATTERNS:
        if pat.search(purpose or ""):
            return etype
    return EventType.OTHER


def _parse_date(s: str) -> date | None:
    """Parse NSE date strings (can be '22-Apr-2026' or '2026-04-22' or similar)."""
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def fetch_upcoming_events() -> list[dict]:
    """Pull upcoming corporate meetings/actions from NSE. Returns raw dicts."""
    try:
        with httpx.Client(headers=NSE_HEADERS, timeout=30.0, follow_redirects=True) as client:
            client.get(NSE_HOME)
            resp = client.get(NSE_MEETINGS_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("nse_meetings_failed", error=str(e))
        return []

    if isinstance(data, dict):
        data = data.get("data", [])
    if not isinstance(data, list):
        return []
    return data


def _build_stock_lookup() -> dict[str, Stock]:
    """Map NSE symbol → Stock for quick lookup."""
    lookup: dict[str, Stock] = {}
    with get_session() as s:
        stocks = s.scalars(select(Stock).where(Stock.currently_active.is_(True))).all()
        for stock in stocks:
            s.expunge(stock)
            lookup[stock.nse_symbol.upper()] = stock
            lookup[stock.symbol.upper()] = stock
    return lookup


def store_events(raw: list[dict]) -> dict:
    """Persist matching events to corporate_events."""
    if not raw:
        return {"total": 0, "matched": 0, "inserted": 0}

    lookup = _build_stock_lookup()
    rows = []
    seen_keys: set[tuple[int, str, date]] = set()  # dedup within batch

    for ev in raw:
        symbol = (ev.get("symbol") or "").strip().upper()
        stock = lookup.get(symbol)
        if not stock:
            continue

        # NSE field names vary: try multiple
        date_str = (
            ev.get("bm_date") or ev.get("meetingDate") or ev.get("date") or ev.get("bmDate")
        )
        event_date = _parse_date(str(date_str) if date_str else "")
        if not event_date:
            continue

        purpose = ev.get("purpose") or ev.get("bm_desc") or ev.get("description") or ""
        purpose = str(purpose).strip()
        event_type = _classify(purpose)

        # dedup
        key = (stock.id, purpose[:50], event_date)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        status = EventStatus.UPCOMING if event_date >= date.today() else EventStatus.COMPLETED
        source_id = f"nse_{symbol}_{event_date.isoformat()}_{event_type.value}_{hash(purpose) % 100000}"

        rows.append({
            "stock_id": stock.id,
            "event_type": event_type.value,
            "event_date": event_date,
            "status": status.value,
            "title": f"{stock.symbol} — {purpose[:100]}",
            "description": purpose,
            "source": "nse",
            "source_id": source_id,
            "metadata_json": {k: v for k, v in ev.items() if v is not None},
        })

    if not rows:
        return {"total": len(raw), "matched": 0, "inserted": 0}

    # Upsert — ignore duplicates by source_id (we pre-dedup'd in Python already)
    with get_session() as s:
        # filter out already-inserted
        existing = {
            r.source_id
            for r in s.execute(
                select(CorporateEvent.source_id).where(
                    CorporateEvent.source == "nse",
                    CorporateEvent.source_id.in_([r["source_id"] for r in rows]),
                )
            ).all()
        }
        new_rows = [r for r in rows if r["source_id"] not in existing]

        if new_rows:
            stmt = mysql_insert(CorporateEvent).values(new_rows)
            stmt = stmt.on_duplicate_key_update(
                status=stmt.inserted.status,
                description=stmt.inserted.description,
                updated_at=datetime.utcnow(),
            )
            s.execute(stmt)

    return {"total": len(raw), "matched": len(rows), "inserted": len(new_rows) if rows else 0}


def ingest_events() -> dict:
    raw = fetch_upcoming_events()
    logger.info("nse_meetings_raw", total=len(raw))
    result = store_events(raw)
    logger.info(
        "nse_meetings_stored",
        matched=result["matched"],
        inserted=result["inserted"],
    )
    return result
