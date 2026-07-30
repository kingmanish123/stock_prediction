"""LLM-based theme extraction from news articles.

Given a news article, asks Gemini to return structured JSON:
  - theme_key:       canonical tag (e.g., 'crude_oil_supply') or 'other'
  - theme_label:     one-line human description
  - direction:       bullish | bearish | neutral (for Indian markets)
  - magnitude:       0.0–1.0 (size of expected impact)
  - confidence:      0.0–1.0 (model's self-reported confidence)
  - affected_sectors:  list of canonical sector keys
  - affected_tickers:  list of NSE symbols
  - reasoning:       1-3 sentence chain-of-thought

Extractions are persisted to `news_themes`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from ..common import config
from ..common.logger import get_logger
from ..common.sector_taxonomy import CANONICAL_SECTORS, THEMES_TO_SECTORS
from ..db.models import NewsArticle, NewsTheme, Stock
from ..db.session import get_session

logger = get_logger(__name__)


# Cost: Gemini 2.5 Flash pricing
# Input: $0.075 / 1M tokens
# Output: $0.30 / 1M tokens
# INR = USD * 84
GEMINI_FLASH_INPUT_USD = 0.075 / 1_000_000
GEMINI_FLASH_OUTPUT_USD = 0.30 / 1_000_000
USD_TO_INR = 84.0

SYSTEM_PROMPT = """You are a financial analyst for the Indian stock market. \
You read one news article at a time and extract a structured insight that helps \
predict which Indian-listed stocks will move today.

Your extraction must:
1. Identify the dominant narrative/theme
2. Classify directional impact on Indian markets (bullish = likely to push indices/stocks up; \
bearish = down; neutral = minimal impact)
3. Assess magnitude realistically — most daily news is NOT major (use low values)
4. Identify affected sectors from our taxonomy
5. Identify specific NSE stocks if directly named or clearly implied (e.g., a crude oil supply \
disruption implies upstream oil names like ONGC, OIL, RIL's E&P segment)
6. Give brief reasoning (2-3 sentences max)

CRITICAL: Only mark direction as bullish/bearish if you're ≥40% confident. Otherwise use neutral.
Magnitude should be 0.1-0.3 for typical company news, 0.4-0.7 for sector-level events, \
0.7-1.0 only for major macro shocks (wars, elections, rate decisions).
"""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "theme_key": {"type": "STRING", "description": "One of known theme keys or 'other'"},
        "theme_label": {"type": "STRING", "description": "One-sentence human description"},
        "direction": {"type": "STRING", "enum": ["bullish", "bearish", "neutral"]},
        "magnitude": {"type": "NUMBER", "description": "0.0-1.0 size of expected impact"},
        "confidence": {"type": "NUMBER", "description": "0.0-1.0 your confidence"},
        "affected_sectors": {"type": "ARRAY", "items": {"type": "STRING"}},
        "affected_tickers": {"type": "ARRAY", "items": {"type": "STRING"}},
        "reasoning": {"type": "STRING", "description": "2-3 sentence explanation"},
    },
    "required": [
        "theme_key", "theme_label", "direction", "magnitude", "confidence",
        "affected_sectors", "affected_tickers", "reasoning",
    ],
}


@dataclass
class ThemeExtraction:
    article_id: int
    theme_key: str
    theme_label: str
    direction: str
    magnitude: float
    confidence: float
    affected_sectors: list[str]
    affected_tickers: list[str]
    validated_tickers: list[str]
    reasoning: str
    tokens_in: int
    tokens_out: int
    cost_inr: Decimal


def _build_prompt(article: NewsArticle, known_tickers: set[str]) -> str:
    """Build the user prompt for the LLM."""
    sector_list = ", ".join(sorted(CANONICAL_SECTORS.keys()))
    theme_list = ", ".join(sorted(THEMES_TO_SECTORS.keys()) + ["other"])

    content = article.content or article.summary or ""
    # Truncate super long content to control cost
    if len(content) > 3000:
        content = content[:3000] + "...[truncated]"

    return f"""{SYSTEM_PROMPT}

AVAILABLE SECTOR KEYS (pick from these only): {sector_list}

KNOWN THEME KEYS (pick one, or 'other' if none fits): {theme_list}

ARTICLE:
Source: {article.source}
Published: {article.published_at}
Title: {article.title}
Summary/Content:
{content}

Return JSON with the schema. For affected_tickers, use NSE symbols (no suffix needed).
"""


class ThemeExtractor:
    """Wraps Gemini calls with validation + cost tracking."""

    def __init__(self, model_name: str | None = None):
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.model_name = model_name or config.LLM_BULK_MODEL
        self._known_tickers: set[str] | None = None

    def _load_known_tickers(self) -> set[str]:
        if self._known_tickers is None:
            with get_session() as s:
                rows = s.scalars(
                    select(Stock.symbol).where(Stock.currently_active.is_(True))
                ).all()
            self._known_tickers = {r.upper() for r in rows}
        return self._known_tickers

    def extract(self, article: NewsArticle) -> ThemeExtraction | None:
        """Call Gemini once for a single article."""
        known = self._load_known_tickers()
        prompt = _build_prompt(article, known)

        try:
            resp = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,
                    temperature=0.1,
                ),
            )
        except genai_errors.APIError as e:
            logger.warning(
                "gemini_api_error", article_id=article.id, error=str(e)[:200]
            )
            return None
        except Exception as e:
            logger.warning(
                "gemini_unknown_error", article_id=article.id, error=str(e)[:200]
            )
            return None

        try:
            parsed = json.loads(resp.text)
        except json.JSONDecodeError:
            logger.warning("gemini_json_parse_failed", article_id=article.id)
            return None

        # Validate sectors + tickers
        affected_sectors = [s for s in parsed.get("affected_sectors", []) if s in CANONICAL_SECTORS]
        raw_tickers = [str(t).strip().upper() for t in parsed.get("affected_tickers", []) if t]
        validated_tickers = [t for t in raw_tickers if t in known]

        # Cost tracking — usage metadata from Gemini
        tokens_in = 0
        tokens_out = 0
        usage = getattr(resp, "usage_metadata", None)
        if usage:
            tokens_in = usage.prompt_token_count or 0
            tokens_out = usage.candidates_token_count or 0
        cost_usd = tokens_in * GEMINI_FLASH_INPUT_USD + tokens_out * GEMINI_FLASH_OUTPUT_USD
        cost_inr = Decimal(str(round(cost_usd * USD_TO_INR, 6)))

        return ThemeExtraction(
            article_id=article.id,
            theme_key=str(parsed.get("theme_key", "other"))[:50],
            theme_label=str(parsed.get("theme_label", ""))[:300],
            direction=str(parsed.get("direction", "neutral")),
            magnitude=float(max(0.0, min(1.0, parsed.get("magnitude", 0.0)))),
            confidence=float(max(0.0, min(1.0, parsed.get("confidence", 0.0)))),
            affected_sectors=affected_sectors,
            affected_tickers=raw_tickers,
            validated_tickers=validated_tickers,
            reasoning=str(parsed.get("reasoning", ""))[:2000],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_inr=cost_inr,
        )


def persist(extractions: list[ThemeExtraction], model_name: str) -> int:
    """Bulk upsert extractions into news_themes."""
    if not extractions:
        return 0
    rows = [{
        "article_id": e.article_id,
        "theme_key": e.theme_key,
        "theme_label": e.theme_label,
        "direction": e.direction,
        "magnitude": e.magnitude,
        "confidence": e.confidence,
        "affected_sectors": e.affected_sectors,
        "affected_tickers": e.affected_tickers,
        "validated_tickers": e.validated_tickers,
        "reasoning": e.reasoning,
        "llm_provider": "gemini",
        "llm_model": model_name,
        "tokens_in": e.tokens_in,
        "tokens_out": e.tokens_out,
        "cost_inr": e.cost_inr,
    } for e in extractions]

    with get_session() as s:
        stmt = mysql_insert(NewsTheme).values(rows)
        stmt = stmt.on_duplicate_key_update(
            theme_key=stmt.inserted.theme_key,
            theme_label=stmt.inserted.theme_label,
            direction=stmt.inserted.direction,
            magnitude=stmt.inserted.magnitude,
            confidence=stmt.inserted.confidence,
            affected_sectors=stmt.inserted.affected_sectors,
            affected_tickers=stmt.inserted.affected_tickers,
            validated_tickers=stmt.inserted.validated_tickers,
            reasoning=stmt.inserted.reasoning,
            tokens_in=stmt.inserted.tokens_in,
            tokens_out=stmt.inserted.tokens_out,
            cost_inr=stmt.inserted.cost_inr,
        )
        s.execute(stmt)
    return len(rows)


def pending_articles(limit: int | None = None) -> list[NewsArticle]:
    """Articles that don't yet have a NewsTheme row for our active model."""
    with get_session() as s:
        # LEFT JOIN to find articles without extraction
        existing_ids = s.execute(
            select(NewsTheme.article_id).where(NewsTheme.llm_model == config.LLM_BULK_MODEL)
        ).scalars().all()
        existing_set = set(existing_ids)

        q = select(NewsArticle).order_by(NewsArticle.published_at.desc())
        if limit:
            q = q.limit(limit * 3)  # buffer since we filter in Python

        all_articles = s.scalars(q).all()
        # Expunge (safe to use outside session)
        for a in all_articles:
            s.expunge(a)

    pending = [a for a in all_articles if a.id not in existing_set]
    if limit:
        pending = pending[:limit]
    return pending
