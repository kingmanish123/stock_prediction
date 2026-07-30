"""Scrape NSE corporate announcements (free, authoritative source)."""
from __future__ import annotations

from datetime import datetime

import httpx

from ...common.logger import get_logger
from .common import RawArticle, parse_timestamp

logger = get_logger(__name__)

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}

NSE_HOME = "https://www.nseindia.com"
NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"


def fetch_nse_announcements() -> list[RawArticle]:
    """Fetch latest NSE corporate announcements (usually last 24-48 hours)."""
    articles: list[RawArticle] = []

    try:
        with httpx.Client(
            headers=NSE_HEADERS, timeout=30.0, follow_redirects=True
        ) as client:
            # Warm-up request (NSE sets cookies on homepage visit)
            client.get(NSE_HOME)
            resp = client.get(NSE_ANNOUNCEMENTS_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("nse_api_failed", error=str(e))
        return []

    # NSE response is a list of announcement dicts
    if not isinstance(data, list):
        data = data.get("data", []) if isinstance(data, dict) else []

    for item in data:
        try:
            symbol = (item.get("symbol") or "").strip()
            subject = (item.get("desc") or "").strip()
            company = (item.get("sm_name") or "").strip()
            attachment_text = (item.get("attchmntText") or "").strip()
            category = (item.get("sm_industry") or item.get("sm_isin") or "").strip()

            # Build a useful title
            if subject and symbol:
                title = f"[{symbol}] {subject}"
            elif subject:
                title = subject
            elif company:
                title = f"{company} announcement"
            else:
                continue  # skip unusable entries

            published = parse_timestamp(
                item.get("an_dt") or item.get("sort_date") or item.get("dissemDT")
            )

            source_article_id = (
                str(item.get("caseId"))
                if item.get("caseId")
                else f"{symbol}_{item.get('an_dt', '')}"
            )

            # URL (attachment file if present, else generic filings page)
            url = item.get("attchmntFile") or (
                f"{NSE_HOME}/companies-listing/corporate-filings-announcements"
            )

            articles.append(
                RawArticle(
                    source="nse",
                    source_article_id=source_article_id,
                    url=url,
                    title=title,
                    summary=attachment_text[:500] if attachment_text else None,
                    content=attachment_text or None,
                    category=category or "announcement",
                    published_at=published,
                )
            )
        except Exception as e:
            logger.warning("nse_entry_parse_failed", error=str(e))
            continue

    logger.info("nse_fetched", count=len(articles))
    return articles
