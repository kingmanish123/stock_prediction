"""RSS feed aggregator for Indian financial news."""
from __future__ import annotations

import feedparser

from ...common.logger import get_logger
from .common import RawArticle, clean_html, parse_timestamp

logger = get_logger(__name__)

# (source_name, feed_url, category_hint)
RSS_FEEDS: list[tuple[str, str, str]] = [
    ("moneycontrol", "https://www.moneycontrol.com/rss/buzzingstocks.xml", "markets"),
    ("moneycontrol", "https://www.moneycontrol.com/rss/business.xml", "business"),
    ("moneycontrol", "https://www.moneycontrol.com/rss/marketreports.xml", "markets"),
    ("moneycontrol", "https://www.moneycontrol.com/rss/results.xml", "results"),
    (
        "et",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "markets",
    ),
    (
        "et",
        "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms",
        "stocks",
    ),
    ("livemint", "https://www.livemint.com/rss/markets", "markets"),
    ("livemint", "https://www.livemint.com/rss/companies", "companies"),
    (
        "business_standard",
        "https://www.business-standard.com/rss/markets-106.rss",
        "markets",
    ),
    (
        "business_standard",
        "https://www.business-standard.com/rss/companies-101.rss",
        "companies",
    ),
]


def fetch_one_feed(source: str, url: str, category_hint: str) -> list[RawArticle]:
    articles: list[RawArticle] = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            summary = clean_html(entry.get("summary") or entry.get("description"))
            published = parse_timestamp(
                entry.get("published_parsed") or entry.get("published")
            )
            articles.append(
                RawArticle(
                    source=source,
                    source_article_id=entry.get("id") or entry.get("guid") or entry.get("link"),
                    url=entry.get("link"),
                    title=title,
                    summary=summary,
                    author=entry.get("author"),
                    category=entry.get("category") or category_hint,
                    published_at=published,
                )
            )
    except Exception as e:
        logger.warning("rss_feed_failed", source=source, url=url, error=str(e))
    return articles


def fetch_all_rss() -> list[RawArticle]:
    all_articles: list[RawArticle] = []
    for source, url, category in RSS_FEEDS:
        articles = fetch_one_feed(source, url, category)
        logger.info("rss_fetched", source=source, url=url, count=len(articles))
        all_articles.extend(articles)
    return all_articles
