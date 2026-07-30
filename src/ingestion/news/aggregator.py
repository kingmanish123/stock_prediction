"""Orchestrate all news sources → dedup → persist to news_articles + article_tickers."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from ...common.logger import get_logger
from ...db.models import ArticleTicker, ExtractionMethod, NewsArticle
from ...db.session import get_session
from . import finnhub_client, nse_scraper, rss_feeds
from .common import RawArticle
from .ticker_extractor import get_extractor

logger = get_logger(__name__)


def dedup_batch(articles: list[RawArticle]) -> list[RawArticle]:
    """In-batch dedup by content_hash (first occurrence wins)."""
    seen: set[str] = set()
    unique: list[RawArticle] = []
    for a in articles:
        h = a.content_hash()
        if h in seen:
            continue
        seen.add(h)
        unique.append(a)
    return unique


def _persist_articles(session, articles: list[RawArticle]) -> dict[str, int]:
    """Bulk upsert articles. Returns map of content_hash → article_id."""
    if not articles:
        return {}

    rows = []
    hash_to_article: dict[str, RawArticle] = {}
    for a in articles:
        h = a.content_hash()
        # dedup within batch by content_hash (first wins)
        if h in hash_to_article:
            continue
        hash_to_article[h] = a

        # truncate string fields to column limits
        sid_raw = a.source_article_id or ""
        sid = sid_raw[:250] if sid_raw else None
        url = (a.url or "")[:1024] or None
        title = (a.title or "").strip()
        author = (a.author or "")[:250] or None
        category = (a.category or "")[:100] or None

        rows.append(
            {
                "source": a.source[:50],
                "source_article_id": sid,
                "url": url,
                "title": title,
                "summary": a.summary,
                "content": a.content,
                "author": author,
                "category": category,
                "published_at": a.published_at,
                "language": a.language[:10] if a.language else "en",
                "content_hash": h,
                "is_processed": False,
            }
        )

    # MySQL ON DUPLICATE KEY UPDATE: if content_hash already exists, just bump fetched_at.
    # content_hash is UNIQUE, so duplicates are filtered at DB level.
    stmt = mysql_insert(NewsArticle).values(rows)
    stmt = stmt.on_duplicate_key_update(fetched_at=datetime.utcnow())
    session.execute(stmt)
    session.flush()

    # Look up article ids by content_hash (inserted or existing)
    hashes = list(hash_to_article.keys())
    rows = session.execute(
        select(NewsArticle.id, NewsArticle.content_hash)
        .where(NewsArticle.content_hash.in_(hashes))
    ).all()
    return {r.content_hash: r.id for r in rows}


def _persist_ticker_mentions(
    session, articles: list[RawArticle], hash_to_id: dict[str, int]
) -> int:
    """Run ticker extractor on each article; bulk upsert article_tickers. Returns total mentions."""
    extractor = get_extractor()

    rows = []
    for a in articles:
        article_id = hash_to_id.get(a.content_hash())
        if not article_id:
            continue
        text = (a.title or "") + " \n " + (a.summary or a.content or "")
        mentions = extractor.extract(text)
        for m in mentions:
            rows.append(
                {
                    "article_id": article_id,
                    "stock_id": m.stock_id,
                    "mention_confidence": round(m.confidence, 3),
                    "extraction_method": ExtractionMethod.RULE_BASED.value,
                }
            )

    if not rows:
        return 0

    stmt = mysql_insert(ArticleTicker).values(rows)
    stmt = stmt.on_duplicate_key_update(
        mention_confidence=stmt.inserted.mention_confidence,
    )
    session.execute(stmt)
    return len(rows)


def ingest_all(sources: list[str] | None = None) -> dict:
    """Run ingestion across requested sources.

    Returns a stats dict: {
        'articles_fetched', 'articles_unique', 'articles_persisted',
        'ticker_mentions', 'by_source'
    }
    """
    if sources is None:
        sources = ["rss", "nse", "finnhub"]

    stats: dict = {
        "articles_fetched": 0,
        "articles_unique": 0,
        "articles_persisted": 0,
        "ticker_mentions": 0,
        "by_source": {},
    }

    all_articles: list[RawArticle] = []

    if "rss" in sources:
        logger.info("ingest_source", source="rss")
        arts = rss_feeds.fetch_all_rss()
        stats["by_source"]["rss"] = len(arts)
        all_articles.extend(arts)

    if "nse" in sources:
        logger.info("ingest_source", source="nse")
        arts = nse_scraper.fetch_nse_announcements()
        stats["by_source"]["nse"] = len(arts)
        all_articles.extend(arts)

    if "finnhub" in sources:
        logger.info("ingest_source", source="finnhub")
        arts = finnhub_client.fetch_general_news()
        stats["by_source"]["finnhub"] = len(arts)
        all_articles.extend(arts)

    stats["articles_fetched"] = len(all_articles)

    unique = dedup_batch(all_articles)
    stats["articles_unique"] = len(unique)
    logger.info("dedup_complete", input=len(all_articles), output=len(unique))

    if not unique:
        return stats

    with get_session() as session:
        hash_to_id = _persist_articles(session, unique)
        stats["articles_persisted"] = len(hash_to_id)
        stats["ticker_mentions"] = _persist_ticker_mentions(session, unique, hash_to_id)

    return stats
