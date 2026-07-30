"""Finnhub news + earnings calendar ingestion."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import finnhub

from ...common.config import FINNHUB_API_KEY
from ...common.logger import get_logger
from .common import RawArticle, parse_timestamp

logger = get_logger(__name__)


def _client():
    if not FINNHUB_API_KEY:
        return None
    return finnhub.Client(api_key=FINNHUB_API_KEY)


def fetch_general_news() -> list[RawArticle]:
    """Free-tier: general business + market news headlines."""
    client = _client()
    if client is None:
        logger.warning("finnhub_no_key")
        return []

    articles: list[RawArticle] = []
    try:
        news = client.general_news("general", min_id=0) or []
    except Exception as e:
        logger.error("finnhub_general_news_failed", error=str(e))
        return []

    for item in news:
        headline = (item.get("headline") or "").strip()
        if not headline:
            continue
        published = parse_timestamp(item.get("datetime"))
        articles.append(
            RawArticle(
                source="finnhub",
                source_article_id=str(item.get("id", "")) or item.get("url"),
                url=item.get("url"),
                title=headline,
                summary=(item.get("summary") or "").strip() or None,
                category=(item.get("category") or "general").strip(),
                published_at=published,
            )
        )

    logger.info("finnhub_fetched", count=len(articles))
    return articles


def fetch_earnings_calendar(days_ahead: int = 14) -> list[dict]:
    """Upcoming earnings calendar (free tier supports this for global + US)."""
    client = _client()
    if client is None:
        return []

    today = date.today()
    end = today + timedelta(days=days_ahead)
    try:
        result = client.earnings_calendar(
            _from=str(today), to=str(end), symbol="", international=True
        )
        return result.get("earningsCalendar", []) or []
    except Exception as e:
        logger.error("finnhub_earnings_calendar_failed", error=str(e))
        return []
