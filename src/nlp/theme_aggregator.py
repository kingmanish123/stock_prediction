"""Aggregate news themes for a target trading day.

For a given target_date, looks at news_themes extracted from articles published
in the pre-market window (last ~18-24 hours before market open) and rolls them up
into ranked "dominant themes for the day."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects import mysql

from ..common.logger import get_logger
from ..db.models import NewsArticle, NewsTheme, ThemeDirection
from ..db.session import get_session

logger = get_logger(__name__)


@dataclass
class ThemeAggregate:
    """Rolled-up view of a theme from multiple news articles."""

    theme_key: str
    theme_label: str                   # representative label (highest-confidence article)
    direction: str                      # bullish | bearish | neutral (majority-weighted)
    direction_score: float              # -1.0 (fully bearish) to +1.0 (fully bullish)
    article_count: int
    source_count: int                   # how many distinct sources mentioned this theme
    avg_magnitude: float
    avg_confidence: float
    max_magnitude: float
    affected_sectors: list[str]         # union across articles
    validated_tickers: list[str]        # union across articles (deduped)
    direct_mention_tickers: dict[str, int]  # ticker → count of articles mentioning
    strength: float                     # composite strength score
    representative_reasoning: str       # reasoning from the top article
    representative_article_id: int

    def summary(self) -> str:
        return (
            f"[{self.theme_key}] {self.direction.upper()} ({self.direction_score:+.2f}) — "
            f"{self.article_count} articles, strength {self.strength:.3f}"
        )


def _direction_to_score(d) -> float:
    """Map direction enum to signed score."""
    val = d.value if hasattr(d, "value") else str(d)
    return {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}.get(val, 0.0)


def _premarket_window(target_date: date) -> tuple[datetime, datetime]:
    """News window: previous trading day 3:30 PM IST → target_date 8:00 AM IST.

    Weekends compress: Monday's window starts Friday 3:30 PM.
    """
    # Default: previous calendar day afternoon + overnight + morning
    window_end = datetime.combine(target_date, time(8, 0))
    # For Monday, look back to Friday. For Tue-Fri, look back to yesterday.
    if target_date.weekday() == 0:  # Monday
        lookback_days = 3
    else:
        lookback_days = 1
    window_start = datetime.combine(
        target_date - timedelta(days=lookback_days), time(15, 30)
    )
    return window_start, window_end


def aggregate_themes_for_date(
    target_date: date,
    min_articles: int = 1,
    min_magnitude: float = 0.0,
) -> list[ThemeAggregate]:
    """Roll up news_themes for the pre-market window of target_date.

    Returns themes sorted by strength (desc). Weak/noisy themes can be filtered
    via `min_articles` and `min_magnitude`.
    """
    window_start, window_end = _premarket_window(target_date)
    logger.info(
        "aggregator_window", target_date=str(target_date),
        window_start=str(window_start), window_end=str(window_end),
    )

    # Pull all extractions in window
    with get_session() as s:
        rows = s.execute(
            select(
                NewsTheme.id,
                NewsTheme.article_id,
                NewsTheme.theme_key,
                NewsTheme.theme_label,
                NewsTheme.direction,
                NewsTheme.magnitude,
                NewsTheme.confidence,
                NewsTheme.affected_sectors,
                NewsTheme.validated_tickers,
                NewsTheme.reasoning,
                NewsArticle.source,
                NewsArticle.published_at,
                NewsArticle.title,
            )
            .join(NewsArticle, NewsArticle.id == NewsTheme.article_id)
            .where(
                NewsArticle.published_at >= window_start,
                NewsArticle.published_at < window_end,
            )
        ).all()

    if not rows:
        logger.warning("aggregator_no_themes_in_window")
        return []

    df = pd.DataFrame(rows, columns=[
        "id", "article_id", "theme_key", "theme_label", "direction",
        "magnitude", "confidence", "affected_sectors", "validated_tickers",
        "reasoning", "source", "published_at", "title",
    ])
    df["direction"] = df["direction"].apply(
        lambda d: d.value if hasattr(d, "value") else str(d)
    )
    df["direction_score"] = df["direction"].map({"bullish": 1.0, "bearish": -1.0, "neutral": 0.0})
    df["magnitude"] = df["magnitude"].astype(float)
    df["confidence"] = df["confidence"].astype(float)
    df["signal_strength"] = df["magnitude"] * df["confidence"]  # per-article strength

    logger.info("aggregator_articles_in_window", count=len(df))

    aggregates: list[ThemeAggregate] = []
    for theme_key, group in df.groupby("theme_key"):
        if len(group) < min_articles:
            continue
        if group["magnitude"].max() < min_magnitude:
            continue

        # Weighted direction = sum(direction_score * signal_strength) / sum(signal_strength)
        weights = group["signal_strength"].clip(lower=0.01)
        weighted_dir = float((group["direction_score"] * weights).sum() / weights.sum())

        if weighted_dir > 0.15:
            dominant_dir = "bullish"
        elif weighted_dir < -0.15:
            dominant_dir = "bearish"
        else:
            dominant_dir = "neutral"

        # Representative article = highest signal_strength
        rep_idx = group["signal_strength"].idxmax()
        rep = group.loc[rep_idx]

        # Sector / ticker unions
        all_sectors: set[str] = set()
        all_tickers: dict[str, int] = {}
        for sectors in group["affected_sectors"]:
            if isinstance(sectors, list):
                all_sectors.update(sectors)
        for tickers in group["validated_tickers"]:
            if isinstance(tickers, list):
                for t in tickers:
                    all_tickers[t] = all_tickers.get(t, 0) + 1

        # Strength score: log(articles) × avg signal × source diversity factor
        src_count = group["source"].nunique()
        import math
        article_weight = math.log1p(len(group))  # log(1+n) — more articles = diminishing returns
        source_diversity = min(src_count / 3.0, 1.5)  # 3 sources = full weight, cap at 1.5x
        strength = float(article_weight * group["signal_strength"].mean() * source_diversity)

        aggregates.append(ThemeAggregate(
            theme_key=str(theme_key) if theme_key else "other",
            theme_label=str(rep["theme_label"]),
            direction=dominant_dir,
            direction_score=weighted_dir,
            article_count=len(group),
            source_count=src_count,
            avg_magnitude=float(group["magnitude"].mean()),
            avg_confidence=float(group["confidence"].mean()),
            max_magnitude=float(group["magnitude"].max()),
            affected_sectors=sorted(all_sectors),
            validated_tickers=sorted(all_tickers.keys()),
            direct_mention_tickers=all_tickers,
            strength=strength,
            representative_reasoning=str(rep["reasoning"]),
            representative_article_id=int(rep["article_id"]),
        ))

    aggregates.sort(key=lambda a: a.strength, reverse=True)
    return aggregates
