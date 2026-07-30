"""Rule-based detection of Nifty 50 stock mentions in news text.

Builds an alias map from:
  • stock symbols (e.g., "RELIANCE")
  • stock names (e.g., "Reliance Industries")
  • hardcoded common abbreviations (e.g., "RIL", "HUL", "L&T")

Returns per-stock mentions with a confidence score based on match specificity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select

from ...db.models import Stock
from ...db.session import get_session

# Hardcoded aliases — common market-speak abbreviations + alternate forms.
# Map: canonical NSE symbol → list of aliases (case-insensitive).
HARDCODED_ALIASES: dict[str, list[str]] = {
    "RELIANCE": ["reliance industries", "reliance ind", "ril"],
    "TCS": ["tata consultancy services", "tata consultancy"],
    "HDFCBANK": ["hdfc bank"],
    "ICICIBANK": ["icici bank"],
    "SBIN": ["state bank of india", "state bank", "sbi"],
    "KOTAKBANK": ["kotak mahindra bank", "kotak mahindra", "kotak bank"],
    "AXISBANK": ["axis bank"],
    "BAJFINANCE": ["bajaj finance"],
    "BAJAJFINSV": ["bajaj finserv"],
    "BAJAJ-AUTO": ["bajaj auto"],
    "M&M": ["mahindra and mahindra", "mahindra & mahindra", "m&m auto"],
    "MARUTI": ["maruti suzuki", "maruti"],
    "TATAMOTORS": ["tata motors"],
    "TATASTEEL": ["tata steel"],
    "TATACONSUM": ["tata consumer products", "tata consumer"],
    "HINDUNILVR": ["hindustan unilever", "hul"],
    "LT": ["larsen and toubro", "larsen & toubro", "l&t"],
    "SUNPHARMA": ["sun pharmaceutical", "sun pharma"],
    "ONGC": ["oil and natural gas corporation"],
    "BPCL": ["bharat petroleum corporation", "bharat petroleum"],
    "COALINDIA": ["coal india"],
    "POWERGRID": ["power grid corporation", "powergrid"],
    "JSWSTEEL": ["jsw steel"],
    "ADANIENT": ["adani enterprises"],
    "ADANIPORTS": ["adani ports", "adani ports and sez"],
    "ASIANPAINT": ["asian paints"],
    "ULTRACEMCO": ["ultratech cement"],
    "NESTLEIND": ["nestle india"],
    "HINDALCO": ["hindalco industries"],
    "GRASIM": ["grasim industries"],
    "INFY": ["infosys"],
    "HCLTECH": ["hcl technologies", "hcl tech"],
    "TECHM": ["tech mahindra"],
    "LTIM": ["ltimindtree"],
    "SHRIRAMFIN": ["shriram finance"],
    "JIOFIN": ["jio financial services", "jio financial"],
    "BHARTIARTL": ["bharti airtel"],
    "DRREDDY": ["dr reddy's laboratories", "dr. reddy's laboratories", "dr reddy", "dr. reddy"],
    "CIPLA": ["cipla ltd"],
    "DIVISLAB": ["divi's laboratories", "divis laboratories", "divi's lab", "divis lab"],
    "APOLLOHOSP": ["apollo hospitals enterprise", "apollo hospitals", "apollo hospital"],
    "SBILIFE": ["sbi life insurance", "sbi life"],
    "HDFCLIFE": ["hdfc life insurance", "hdfc life"],
    "BRITANNIA": ["britannia industries"],
    "HEROMOTOCO": ["hero motocorp", "hero moto"],
    "EICHERMOT": ["eicher motors"],
    "INDUSINDBK": ["indusind bank"],
    "TITAN": ["titan company"],
    "BEL": ["bharat electronics"],
    "TRENT": ["trent ltd"],
    "ADANIGREEN": ["adani green energy", "adani green"],
}

# Words that are too short or ambiguous to match on their own
AMBIGUOUS_SHORT_TOKENS = {"itc", "bel", "lt", "sbi", "bse", "nse", "oil", "gic", "dcm", "ioc"}

# Common company-name suffixes that should be stripped before matching.
# Order matters — longer suffixes first (check ".co." before "co.").
COMPANY_NAME_SUFFIXES = (
    " limited",
    " ltd.",
    " ltd",
    " pvt. ltd.",
    " pvt ltd",
    " (india)",
    " india ltd",
    " india limited",
    " corporation ltd",
    " corporation limited",
    " corporation",
    " corp.",
    " corp",
    " company",
    " co.",
    " industries",
    " industries ltd",
    " technologies",
    " technologies ltd",
    " enterprises",
    " enterprises ltd",
    " holdings",
    " holdings ltd",
    " finance",
    " financial services",
    " financial",
    " motors",
    " motors ltd",
    " steel",
    " cement",
    " pharmaceuticals",
    " pharmaceutical",
    " pharma",
    " bank",
    " bank ltd",
    " insurance",
    " consumer products",
    " consumer",
    " international",
    " group",
    " inc.",
    " inc",
)


def _strip_name_suffix(name: str) -> str:
    """Strip common suffixes iteratively — handles 'XYZ Industries Ltd.' → 'XYZ'."""
    n = name.lower().strip()
    changed = True
    while changed:
        changed = False
        for suffix in COMPANY_NAME_SUFFIXES:
            if n.endswith(suffix):
                n = n[: -len(suffix)].strip()
                changed = True
                break
    return n


@dataclass
class TickerMention:
    stock_id: int
    symbol: str
    confidence: float
    matched_alias: str


class TickerExtractor:
    """Builds an alias → stock map and extracts mentions from text."""

    def __init__(self) -> None:
        # list of (compiled pattern, stock_id, symbol, alias, confidence)
        self._patterns: list[tuple[re.Pattern, int, str, str, float]] = []
        self._loaded = False

    def load(self) -> None:
        with get_session() as s:
            stocks = s.scalars(
                select(Stock).where(Stock.currently_active.is_(True))
            ).all()

            for stock in stocks:
                aliases: dict[str, float] = {}  # alias → confidence

                # 1. Symbol itself (high confidence if >= 4 chars)
                sym_lower = stock.symbol.lower()
                conf = 0.95 if len(sym_lower) >= 4 and sym_lower not in AMBIGUOUS_SHORT_TOKENS else 0.7
                aliases[sym_lower] = conf

                # 2. Full company name minus multiple suffix variants
                stemmed = _strip_name_suffix(stock.name)
                if stemmed and len(stemmed) >= 5:
                    aliases[stemmed] = 1.0

                # 3. Also the first 1-2 significant words (e.g. "Bharat Electronics" → "bharat electronics")
                tokens = stemmed.split()
                # "Dr. Reddy's Laboratories" → stemmed "dr. reddy's" → short-form "dr reddy"
                if len(tokens) >= 2:
                    two_word = " ".join(tokens[:2]).replace(".", "").replace("'s", "")
                    if len(two_word) >= 6 and two_word != stemmed:
                        aliases[two_word] = 0.85

                # 4. Hardcoded aliases (override confidence)
                for alias in HARDCODED_ALIASES.get(stock.symbol, []):
                    aliases[alias.lower()] = 1.0

                # compile patterns
                for alias, confidence in aliases.items():
                    # word-boundary match (handles "Reliance" in "Reliance Industries" OK)
                    pattern = re.compile(
                        r"(?<![a-zA-Z0-9])" + re.escape(alias) + r"(?![a-zA-Z0-9])",
                        re.IGNORECASE,
                    )
                    self._patterns.append(
                        (pattern, stock.id, stock.symbol, alias, confidence)
                    )

        self._loaded = True

    def extract(self, text: str) -> list[TickerMention]:
        """Return list of unique ticker mentions (highest-confidence per stock)."""
        if not self._loaded:
            self.load()
        if not text:
            return []

        best_by_stock: dict[int, TickerMention] = {}
        for pattern, stock_id, symbol, alias, confidence in self._patterns:
            if pattern.search(text):
                existing = best_by_stock.get(stock_id)
                if existing is None or confidence > existing.confidence:
                    best_by_stock[stock_id] = TickerMention(
                        stock_id=stock_id,
                        symbol=symbol,
                        confidence=confidence,
                        matched_alias=alias,
                    )
        return list(best_by_stock.values())


_extractor: TickerExtractor | None = None


def get_extractor() -> TickerExtractor:
    global _extractor
    if _extractor is None:
        _extractor = TickerExtractor()
        _extractor.load()
    return _extractor
