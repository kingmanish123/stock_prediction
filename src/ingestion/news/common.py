"""Shared helpers for news ingestion: canonical article shape, hashing, normalization."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


@dataclass
class RawArticle:
    source: str
    title: str
    published_at: datetime
    source_article_id: str | None = None
    url: str | None = None
    summary: str | None = None
    content: str | None = None
    author: str | None = None
    category: str | None = None
    language: str = "en"

    def content_hash(self) -> str:
        return compute_content_hash(self.title, self.content or self.summary or "")


_WHITESPACE_RE = re.compile(r"\s+")
_HTML_RE = re.compile(r"<[^>]+>")


def normalize_text(s: str) -> str:
    """Lowercase, strip HTML, collapse whitespace."""
    if not s:
        return ""
    s = _HTML_RE.sub(" ", s)
    s = s.lower().strip()
    s = _WHITESPACE_RE.sub(" ", s)
    return s


def compute_content_hash(title: str, content: str = "") -> str:
    """SHA-256 hash of normalized title + content for dedup."""
    combined = normalize_text(title) + "|" + normalize_text(content)[:500]
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def clean_html(html: str | None) -> str | None:
    if not html:
        return html
    return _HTML_RE.sub("", html).strip()


def parse_timestamp(v) -> datetime:
    """Best-effort datetime parser accepting int/float/str/struct_time."""
    if v is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    # struct_time (from feedparser)
    if hasattr(v, "tm_year"):
        try:
            return datetime(*v[:6])
        except Exception:
            pass

    # unix timestamp
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v)
        except Exception:
            pass

    # string
    if isinstance(v, str):
        # RFC 2822 format (RSS dates)
        try:
            dt = parsedate_to_datetime(v)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            pass
        # ISO and common formats
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%d-%b-%Y %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(v, fmt)
            except ValueError:
                continue

    return datetime.now(timezone.utc).replace(tzinfo=None)
