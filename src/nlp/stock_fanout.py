"""News theme → candidate stocks fanout.

Given a theme aggregate, produce a ranked list of Nifty 100 stocks that
could move because of that theme. Scoring combines:
  - direct LLM mention (highest weight)
  - sector alignment (theme's affected_sectors → stock's canonical sector)
  - recent liquidity (avg turnover)
  - technical momentum (from active XGBoost direction model)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from ..common import config
from ..common.logger import get_logger
from ..common.sector_taxonomy import THEMES_TO_SECTORS
from ..db.models import MarketDataDaily, Stock, StockUniverseHistory
from ..db.session import get_session
from .theme_aggregator import ThemeAggregate

logger = get_logger(__name__)


@dataclass
class StockCandidate:
    stock_id: int
    symbol: str
    name: str
    sector: str
    last_close: float | None
    avg_turnover_cr_20d: float | None

    theme_key: str
    theme_direction: str                  # bullish | bearish (inherited from theme)
    theme_strength: float

    direct_mention_count: int             # how many articles explicitly named this ticker
    sector_aligned: bool                  # is this stock's sector in theme's affected_sectors
    sector_alignment_weight: float        # 1.0 if core, 0.5 if secondary, 0 if not

    # Technical confirmation context (added 2026-04-23 after Day-1 miss analysis)
    return_5d_pct: float | None = None           # recent momentum
    return_20d_pct: float | None = None
    volume_ratio_20d: float | None = None        # confirmation signal

    # Penalty flags (set during score computation)
    rally_penalty: float = 1.0                    # <1.0 if stock already rallied
    volume_penalty: float = 1.0                   # <1.0 if low volume

    # Scoring components
    base_score: float = 0.0                       # from theme × sector alignment × mention
    liquidity_score: float = 0.0                  # 0-1 normalized
    final_score: float = 0.0                      # base × liquidity × rally × volume

    reasoning_hint: str = ""                      # inherited from theme reasoning

    def as_dict(self) -> dict:
        return {k: (v if not isinstance(v, list) else list(v)) for k, v in self.__dict__.items()}


def _universe_stocks(as_of: date) -> list[Stock]:
    """All active stocks in the configured universe (config.UNIVERSE) as of date."""
    universe_name = config.UNIVERSE
    with get_session() as s:
        stocks = s.scalars(
            select(Stock)
            .join(StockUniverseHistory, StockUniverseHistory.stock_id == Stock.id)
            .where(
                StockUniverseHistory.universe_name == universe_name,
                StockUniverseHistory.valid_from <= as_of,
                (StockUniverseHistory.valid_to.is_(None))
                | (StockUniverseHistory.valid_to > as_of),
            )
        ).all()
        for x in stocks:
            s.expunge(x)
    return list(stocks)


def _stock_context(as_of: date, stock_ids: list[int]) -> pd.DataFrame:
    """Fetch recent price + volume context per stock.

    Returns DataFrame with: stock_id, last_close, avg_turnover_cr_20d,
    return_5d_pct, return_20d_pct, volume_ratio_20d.
    """
    lookback = as_of - timedelta(days=45)  # buffer for 20 trading days
    with get_session() as s:
        rows = s.execute(
            select(
                MarketDataDaily.stock_id,
                MarketDataDaily.trade_date,
                MarketDataDaily.close,
                MarketDataDaily.turnover_cr,
                MarketDataDaily.volume,
            )
            .where(
                MarketDataDaily.stock_id.in_(stock_ids),
                MarketDataDaily.trade_date >= lookback,
                MarketDataDaily.trade_date <= as_of,
            )
            .order_by(MarketDataDaily.stock_id, MarketDataDaily.trade_date)
        ).all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        rows, columns=["stock_id", "trade_date", "close", "turnover_cr", "volume"]
    )
    df["close"] = df["close"].astype(float)
    df["turnover_cr"] = df["turnover_cr"].astype(float)
    df["volume"] = df["volume"].fillna(0).astype(float)
    df = df.sort_values(["stock_id", "trade_date"]).reset_index(drop=True)

    context_rows: list[dict] = []
    for stock_id, group in df.groupby("stock_id"):
        g = group.reset_index(drop=True)
        if g.empty:
            continue
        last_close = float(g["close"].iloc[-1])
        return_5d = None
        if len(g) >= 6:
            c5 = float(g["close"].iloc[-6])
            if c5 > 0:
                return_5d = (last_close / c5) - 1
        return_20d = None
        if len(g) >= 21:
            c20 = float(g["close"].iloc[-21])
            if c20 > 0:
                return_20d = (last_close / c20) - 1
        avg_turnover = float(g["turnover_cr"].tail(20).mean()) if len(g) >= 2 else None
        volume_ratio = None
        if len(g) >= 21:
            last_vol = float(g["volume"].iloc[-1])
            prior_mean = float(g["volume"].iloc[-21:-1].mean())
            if prior_mean > 0:
                volume_ratio = last_vol / prior_mean

        context_rows.append({
            "stock_id": stock_id,
            "last_close": last_close,
            "avg_turnover_cr_20d": avg_turnover,
            "return_5d_pct": return_5d * 100 if return_5d is not None else None,
            "return_20d_pct": return_20d * 100 if return_20d is not None else None,
            "volume_ratio_20d": volume_ratio,
        })

    return pd.DataFrame(context_rows)


def _rally_penalty(return_5d_pct: float | None, return_20d_pct: float | None) -> float:
    """Discount score when stock has already rallied — mean reversion risk.

    Derived from 2026-04-22 miss analysis (HYUNDAI up 8%/5d → reverted -1.6%).
      - return_5d_pct > 10%  → 0.60 (strongest penalty — crowded short-term)
      - return_5d_pct > 5%   → 0.80
      - return_20d_pct > 20% → 0.70 (strong medium-term exhaustion)
      - return_20d_pct > 12% → 0.85
      - otherwise            → 1.0

    5d and 20d are both checked; the most punitive applicable value wins.
    """
    factors: list[float] = []
    if return_5d_pct is not None:
        if return_5d_pct > 10:
            factors.append(0.60)
        elif return_5d_pct > 5:
            factors.append(0.80)
    if return_20d_pct is not None:
        if return_20d_pct > 20:
            factors.append(0.70)
        elif return_20d_pct > 12:
            factors.append(0.85)
    return min(factors) if factors else 1.0


def _volume_factor(volume_ratio_20d: float | None) -> float:
    """Penalize low-volume bullish picks (no institutional confirmation).

    Derived from 2026-04-22 miss analysis (TITAN vol 0.47, MARUTI 0.49):
      - ratio < 0.5 → 0.70
      - ratio 0.5–0.7 → 0.85
      - ratio 0.7–1.5 → 1.0
      - ratio > 1.5 → 1.10 (mild boost — institutional interest)
    """
    if volume_ratio_20d is None:
        return 1.0
    if volume_ratio_20d < 0.5:
        return 0.70
    if volume_ratio_20d < 0.7:
        return 0.85
    if volume_ratio_20d > 1.5:
        return 1.10
    return 1.0


def find_candidates_for_theme(
    theme: ThemeAggregate,
    as_of: date,
    max_candidates: int = 30,
) -> list[StockCandidate]:
    """Generate ranked candidates for a single theme."""

    if theme.direction == "neutral":
        return []  # neutral themes don't imply directional bets

    stocks = _universe_stocks(as_of)
    stock_ids = [s.id for s in stocks]
    if not stocks:
        return []

    ctx = _stock_context(as_of, stock_ids)
    ctx_map = {row.stock_id: row for row in ctx.itertuples()} if not ctx.empty else {}

    # Determine theme's target sectors
    theme_sectors = set(theme.affected_sectors or [])
    # Fallback: use THEMES_TO_SECTORS if theme_key is canonical but sectors empty
    if not theme_sectors and theme.theme_key in THEMES_TO_SECTORS:
        theme_sectors = set(THEMES_TO_SECTORS[theme.theme_key])

    candidates: list[StockCandidate] = []

    # Compute max turnover for liquidity normalization
    max_turnover = ctx["avg_turnover_cr_20d"].max() if not ctx.empty else 1.0
    max_turnover = max(max_turnover, 1.0)

    for stock in stocks:
        direct_count = theme.direct_mention_tickers.get(stock.symbol, 0)
        stock_sector = stock.sector or "other"
        sector_aligned = stock_sector in theme_sectors

        # Skip if neither direct mention nor sector aligned
        if direct_count == 0 and not sector_aligned:
            continue

        alignment_weight = 1.0 if sector_aligned else 0.0
        if direct_count > 0:
            alignment_weight = max(alignment_weight, 1.2)  # direct mention = stronger signal

        # Base score: theme strength × alignment × (1 + direct mention boost)
        mention_boost = min(direct_count * 0.3, 0.9)  # cap at +0.9
        base_score = theme.strength * alignment_weight * (1 + mention_boost)

        # Context
        ctx_row = ctx_map.get(stock.id)
        last_close = ctx_row.last_close if ctx_row else None
        avg_turn = ctx_row.avg_turnover_cr_20d if ctx_row else None
        ret_5d = ctx_row.return_5d_pct if ctx_row else None
        ret_20d = ctx_row.return_20d_pct if ctx_row else None
        vol_ratio = ctx_row.volume_ratio_20d if ctx_row else None

        # Liquidity: log-scaled turnover
        if avg_turn and avg_turn > 0:
            liquidity = math.log1p(avg_turn) / math.log1p(max_turnover)
        else:
            liquidity = 0.3
        liquidity = max(0.1, min(1.0, liquidity))

        # NEW (2026-04-23, Day-1 learnings): rally + volume penalties for BULLISH picks only
        # (bearish themes already imply downside, so rally exhaustion is less relevant there)
        if theme.direction == "bullish":
            rally_pen = _rally_penalty(ret_5d, ret_20d)
            vol_fac = _volume_factor(vol_ratio)
        else:
            rally_pen = 1.0
            vol_fac = 1.0

        final_score = base_score * liquidity * rally_pen * vol_fac

        candidates.append(StockCandidate(
            stock_id=stock.id,
            symbol=stock.symbol,
            name=stock.name,
            sector=stock_sector,
            last_close=last_close,
            avg_turnover_cr_20d=avg_turn,
            theme_key=theme.theme_key,
            theme_direction=theme.direction,
            theme_strength=theme.strength,
            direct_mention_count=direct_count,
            sector_aligned=sector_aligned,
            sector_alignment_weight=alignment_weight,
            return_5d_pct=ret_5d,
            return_20d_pct=ret_20d,
            volume_ratio_20d=vol_ratio,
            rally_penalty=rally_pen,
            volume_penalty=vol_fac,
            base_score=base_score,
            liquidity_score=liquidity,
            final_score=final_score,
            reasoning_hint=theme.representative_reasoning[:500],
        ))

    candidates.sort(key=lambda c: c.final_score, reverse=True)
    return candidates[:max_candidates]


def find_all_candidates(
    themes: list[ThemeAggregate],
    as_of: date,
    per_theme: int = 10,
) -> dict[str, list[StockCandidate]]:
    """Run fanout for every theme. Returns dict: theme_key → candidates."""
    result: dict[str, list[StockCandidate]] = {}
    for theme in themes:
        cands = find_candidates_for_theme(theme, as_of, max_candidates=per_theme)
        if cands:
            result[theme.theme_key] = cands
    return result


def merge_candidates(
    per_theme_candidates: dict[str, list[StockCandidate]],
) -> list[StockCandidate]:
    """Merge per-theme candidates into a single ranked list.

    When the same stock appears under multiple themes, we pick the one with the
    highest final_score and note cumulative direct mentions.
    """
    best_per_stock: dict[int, StockCandidate] = {}
    for theme_key, cands in per_theme_candidates.items():
        for c in cands:
            existing = best_per_stock.get(c.stock_id)
            if existing is None or c.final_score > existing.final_score:
                best_per_stock[c.stock_id] = c

    merged = list(best_per_stock.values())
    merged.sort(key=lambda c: c.final_score, reverse=True)
    return merged
