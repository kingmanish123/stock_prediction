"""Per-stock deep reasoning using Claude.

Given a candidate stock + dominant theme + recent context, asks Claude to
evaluate conviction (1-10) and articulate the case. This is the LLM layer
where we spend more tokens for higher-quality reasoning on our top picks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from anthropic import Anthropic
from sqlalchemy import desc, select

from ..common import config
from ..common.logger import get_logger
from ..db.models import ArticleTicker, MarketDataDaily, NewsArticle, StockFundamentals
from ..db.session import get_session
from ..ml.technical_indicators import compute_ta_snapshot
from .stock_fanout import StockCandidate
from .theme_aggregator import ThemeAggregate

logger = get_logger(__name__)


# Claude Sonnet 4.6 pricing (approximate)
CLAUDE_SONNET_INPUT_USD = 3.0 / 1_000_000
CLAUDE_SONNET_OUTPUT_USD = 15.0 / 1_000_000
USD_TO_INR = 84.0


@dataclass
class StockReasoning:
    stock_id: int
    symbol: str
    conviction: int                    # 1-10 (10 = very high conviction)
    recommendation: str                # BUY | HOLD | AVOID
    primary_reasoning: str             # 1-2 sentence core thesis
    supporting_factors: list[str]      # bullet points
    key_risks: list[str]               # bullet points
    alternative_scenario: str          # what could go wrong
    tokens_in: int
    tokens_out: int
    cost_inr: Decimal


REASONING_SYSTEM_PROMPT = """You are a senior Indian equity analyst. You're given a candidate stock \
that surfaced from today's news themes, and asked to reason carefully about whether it will move \
in the theme's direction tomorrow.

Core rules:
1. Conviction scale: 1-3 = weak/unclear, 4-6 = moderate thesis, 7-8 = strong thesis, 9-10 = very \
strong (rare — needs specific catalyst, not just "sector looks good")
2. BUY only when conviction ≥ 6 AND theme_direction = bullish
3. AVOID when conviction ≥ 6 AND theme_direction = bearish
4. HOLD when conviction < 6 OR direction unclear
5. Think about timing — is move likely to happen TOMORROW specifically, or over weeks?
6. Consider crowding — if news is widely known, edge may be small. Flag this as a risk.
7. Be honest: if the theme doesn't clearly apply to this stock, say so and give low conviction.

TRAP CHECKS (learned from Day-1 miss analysis — apply these mechanically):

8. MEAN-REVERSION TRAP — check return_5d_pct and return_20d_pct:
   • return_5d_pct > 10% → this is a crowded/extended trade. Max conviction = 5. Flag "profit booking risk".
   • return_5d_pct > 5% on bullish theme → reduce conviction by 1-2 points. Flag "recent rally — exhaustion risk".
   • return_20d_pct > 20% → same — crowded/extended. Max conviction 6.
   Historical example: HYUNDAI was up 8% in 5 days on 2026-04-22, then reverted -1.6% the next day.

9. VOLUME CONFIRMATION CHECK — inspect volume_ratio_20d:
   • volume_ratio_20d < 0.5 → ZERO institutional buying. Reduce conviction by 2. Never exceed conviction 4 for BUY.
   • volume_ratio_20d 0.5–0.7 → weak participation. Reduce conviction by 1.
   • volume_ratio_20d > 1.5 → strong institutional interest, confirming bullish thesis. May boost conviction by 1.
   Historical example: TITAN (vol ratio 0.47) and MARUTI (0.49) were low-volume picks on 2026-04-22 — both reverted.

10. STOCK-SPECIFIC NEWS vs PURE THEME BET:
    • If you see 0 recent news articles directly naming this stock, the pick is a pure theme/sector bet.
      → Reduce conviction by 1. The LLM is not a directional prediction without stock-level catalyst.
    • If 2+ articles directly mention this stock AND align with theme direction → boost conviction by 1.
    Historical example: HDFCLIFE had zero pre-market news on 2026-04-22 — theme bet failed -1.65%.

11. PREDICTED RANGE SANITY:
    • If the predicted upside (target - last_close) is smaller than the predicted downside (last_close - stop),
      the risk/reward is bad. Reduce conviction by 1.

12. BEARISH NEWS VETO — look at the `sentiment_breakdown` in the news block:
    • If the stock has >= 3 labeled articles AND >= 60% are negative, set recommendation = AVOID.
      Do NOT BUY a stock whose own news is dominantly bearish, no matter how bullish the theme is.
      Historical example (2026-04-23): HCLTECH had 11 bearish vs 0 bullish articles — predicted UP, lost 1.01%.
      SBI Life had "Q4 profit decline" headline — predicted UP, lost 0.29%.

13. TECHNICAL CHART VETO — look at the `technical_chart` block:
    • If RSI(14) > 75 → OVERBOUGHT. Max conviction 4. Flag "RSI extreme".
    • If RSI(14) < 25 AND near 20d support → OVERSOLD bounce setup. May add +1 conviction.
    • If MACD just crossed bearish (macd_crossover_days is negative AND > -3) → momentum flipped down.
      Max conviction 5 unless there's a strong stock-specific bullish catalyst.
    • If NEAR RESISTANCE (within 2% of 20d high) AND no clear breakout catalyst → price likely rejects.
      Reduce conviction by 1.
    • If price is at/near lower Bollinger band (%b < 0.1) AND RSI oversold → mean-reversion BUY zone,
      may boost conviction by 1.
    • If DEATH CROSS (EMA20 < EMA50) with price > 3% below EMA50 → downtrend, reduce conviction by 1.
      Only override if news catalyst is very strong.

14. FUNDAMENTALS SANITY — look at the `fundamentals` block:
    • If P/E is flagged HIGH (>40) AND revenue growth < 15% → overvalued, not a good intraday long.
      Reduce conviction by 1.
    • If D/E flagged HIGH (>1.0) AND news is macro-negative (rate hike, credit stress) → balance sheet risk.
      Reduce conviction by 1-2.
    • If ROE > 20% AND revenue growth strong (>15%) → quality compounder. May boost conviction by 1 when
      combined with bullish theme.
    • If stock is > 30% below 52-week high AND recent news is positive (earnings beat, upgrade) →
      mean-reversion setup with fundamental floor. May boost conviction by 1.
    • Micro/small-caps (mkt_cap_cr < 5000) are more volatile — require stronger news catalyst. If
      conviction ≥ 7 on a small-cap, the news evidence must be explicit and stock-specific.

Apply these TRAP CHECKS before finalizing conviction. Mention each triggered rule in your reasoning.

Respond with valid JSON matching the requested schema.
"""


def _fetch_stock_news_snippets(stock_id: int, target_date: date, max_items: int = 8) -> list[dict]:
    """Recent news titles + sentiment for this stock (last 3 days)."""
    cutoff = target_date - timedelta(days=3)
    with get_session() as s:
        rows = s.execute(
            select(
                NewsArticle.title,
                NewsArticle.source,
                NewsArticle.published_at,
                NewsArticle.sentiment_label,
            )
            .join(ArticleTicker, ArticleTicker.article_id == NewsArticle.id)
            .where(
                ArticleTicker.stock_id == stock_id,
                NewsArticle.published_at >= cutoff,
            )
            .order_by(desc(NewsArticle.published_at))
            .limit(max_items)
        ).all()
    return [
        {
            "title": r.title[:200],
            "source": r.source,
            "published": str(r.published_at)[:19],
            "sentiment": r.sentiment_label.value if hasattr(r.sentiment_label, "value") else None,
        }
        for r in rows
    ]


def _sentiment_counts(news_snippets: list[dict]) -> dict[str, int]:
    """Count sentiment labels in news snippets."""
    counts = {"positive": 0, "negative": 0, "neutral": 0, "unlabeled": 0}
    for n in news_snippets:
        s = n.get("sentiment")
        if s in counts:
            counts[s] += 1
        else:
            counts["unlabeled"] += 1
    return counts


def is_bearish_news_veto(news_snippets: list[dict], min_articles: int = 3, bearish_ratio: float = 0.6) -> bool:
    """Return True if stock's own news is majority bearish — veto BUY regardless of theme.

    Needs `min_articles` labeled articles AND bearish/(bearish+bullish) >= `bearish_ratio`.
    """
    c = _sentiment_counts(news_snippets)
    labeled = c["positive"] + c["negative"]
    if labeled < min_articles:
        return False
    ratio = c["negative"] / labeled if labeled else 0.0
    return ratio >= bearish_ratio


def _fetch_fundamentals_summary(stock_id: int) -> str | None:
    """Return human-readable fundamentals block for Claude prompt, or None if absent."""
    with get_session() as s:
        f = s.execute(
            select(StockFundamentals)
            .where(StockFundamentals.stock_id == stock_id)
            .order_by(desc(StockFundamentals.snapshot_date))
            .limit(1)
        ).scalar_one_or_none()
    if f is None:
        return None

    parts: list[str] = []
    if f.pe_ratio is not None:
        pe_tag = "HIGH" if f.pe_ratio > 40 else ("LOW" if f.pe_ratio < 15 else "moderate")
        parts.append(f"P/E={f.pe_ratio} [{pe_tag}]")
    if f.forward_pe is not None:
        parts.append(f"fwd P/E={f.forward_pe}")
    if f.peg_ratio is not None:
        parts.append(f"PEG={f.peg_ratio}")
    if f.market_cap_cr is not None:
        cap_cat = (
            "mega-cap" if f.market_cap_cr > 100000 else
            "large-cap" if f.market_cap_cr > 20000 else
            "mid-cap" if f.market_cap_cr > 5000 else
            "small-cap"
        )
        parts.append(f"mkt_cap=₹{float(f.market_cap_cr):,.0f}cr [{cap_cat}]")
    if f.roe is not None:
        roe_pct = float(f.roe) * 100
        parts.append(f"ROE={roe_pct:.1f}%")
    if f.revenue_growth_yoy is not None:
        rg_pct = float(f.revenue_growth_yoy) * 100
        tag = "strong" if rg_pct > 15 else ("weak" if rg_pct < 0 else "modest")
        parts.append(f"rev_growth_yoy={rg_pct:+.1f}% [{tag}]")
    if f.earnings_growth_yoy is not None:
        eg_pct = float(f.earnings_growth_yoy) * 100
        parts.append(f"earn_growth_yoy={eg_pct:+.1f}%")
    if f.debt_to_equity is not None:
        de = float(f.debt_to_equity)
        tag = "HIGH" if de > 1.0 else ("LOW" if de < 0.3 else "moderate")
        parts.append(f"D/E={de:.2f} [{tag}]")
    if f.profit_margin is not None:
        pm_pct = float(f.profit_margin) * 100
        parts.append(f"profit_margin={pm_pct:.1f}%")
    if f.beta is not None:
        parts.append(f"beta={f.beta}")
    if f.fifty_two_week_high is not None and f.fifty_two_week_low is not None and f.current_price is not None:
        hi = float(f.fifty_two_week_high)
        lo = float(f.fifty_two_week_low)
        cur = float(f.current_price)
        pct_from_high = (cur - hi) / hi * 100
        pct_from_low = (cur - lo) / lo * 100
        parts.append(
            f"52w range: ₹{lo:.0f}–₹{hi:.0f} (now {pct_from_high:+.0f}% from high, {pct_from_low:+.0f}% from low)"
        )
    return " | ".join(parts) if parts else None


def _fetch_technical_snapshot(stock_id: int, target_date: date) -> dict:
    """Return dict with close, 5-day, 20-day returns, recent volume ratio."""
    lookback = target_date - timedelta(days=45)
    with get_session() as s:
        rows = s.execute(
            select(MarketDataDaily.trade_date, MarketDataDaily.close, MarketDataDaily.volume)
            .where(
                MarketDataDaily.stock_id == stock_id,
                MarketDataDaily.trade_date >= lookback,
                MarketDataDaily.trade_date <= target_date,
            )
            .order_by(MarketDataDaily.trade_date)
        ).all()

    if not rows or len(rows) < 5:
        return {}

    closes = [float(r.close) for r in rows if r.close is not None]
    volumes = [int(r.volume) for r in rows if r.volume is not None]

    def _pct(a, b):
        return (a / b - 1) if b and b > 0 else None

    last = closes[-1] if closes else None
    ret_1d = _pct(closes[-1], closes[-2]) if len(closes) >= 2 else None
    ret_5d = _pct(closes[-1], closes[-6]) if len(closes) >= 6 else None
    ret_20d = _pct(closes[-1], closes[-21]) if len(closes) >= 21 else None

    # Volume ratio: last vs 20-day avg
    vol_avg_20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else None
    vol_ratio = (volumes[-1] / vol_avg_20) if vol_avg_20 and vol_avg_20 > 0 else None

    return {
        "last_close": round(last, 2) if last else None,
        "return_1d_pct": round(ret_1d * 100, 2) if ret_1d is not None else None,
        "return_5d_pct": round(ret_5d * 100, 2) if ret_5d is not None else None,
        "return_20d_pct": round(ret_20d * 100, 2) if ret_20d is not None else None,
        "volume_ratio_20d": round(vol_ratio, 2) if vol_ratio else None,
    }


def _build_reasoning_prompt(
    candidate: StockCandidate,
    theme: ThemeAggregate,
    news_snippets: list[dict],
    technicals: dict,
    target_date: date,
    ta_summary: str | None = None,
    fundamentals_summary: str | None = None,
) -> str:
    news_block = ""
    news_counts = _sentiment_counts(news_snippets)
    if news_snippets:
        lines = []
        for n in news_snippets:
            sentiment_str = f" [{n['sentiment']}]" if n.get("sentiment") else ""
            lines.append(f"  - [{n['source']} {n['published']}]{sentiment_str} {n['title']}")
        news_block = "\n".join(lines)
        # Append explicit sentiment breakdown — this is what feeds rule #12
        news_block += (
            f"\n\n  sentiment_breakdown: "
            f"positive={news_counts['positive']}, "
            f"negative={news_counts['negative']}, "
            f"neutral={news_counts['neutral']}, "
            f"unlabeled={news_counts['unlabeled']}"
        )
    else:
        news_block = "  (no recent stock-specific news found)\n\n  sentiment_breakdown: none"

    # Build technical block with explicit trap flags
    trap_flags = []
    if technicals:
        r5 = technicals.get("return_5d_pct")
        r20 = technicals.get("return_20d_pct")
        vr = technicals.get("volume_ratio_20d")
        if r5 is not None and r5 > 10:
            trap_flags.append(f"⚠ TRAP: up {r5:+.1f}% in 5d → crowded/extended trade")
        elif r5 is not None and r5 > 5:
            trap_flags.append(f"⚠ CAUTION: up {r5:+.1f}% in 5d → recent rally, mean-reversion risk")
        if r20 is not None and r20 > 20:
            trap_flags.append(f"⚠ TRAP: up {r20:+.1f}% in 20d → exhaustion risk")
        if vr is not None and vr < 0.5:
            trap_flags.append(f"⚠ TRAP: volume ratio {vr:.2f} → zero institutional confirmation")
        elif vr is not None and vr < 0.7:
            trap_flags.append(f"⚠ CAUTION: volume ratio {vr:.2f} → weak institutional interest")
        elif vr is not None and vr > 1.5:
            trap_flags.append(f"✓ BOOST: volume ratio {vr:.2f} → strong institutional interest")

    tech_block = "\n".join([f"  - {k}: {v}" for k, v in technicals.items()]) if technicals else "  (no data)"
    if trap_flags:
        tech_block += "\n\n  TRAP CHECKS triggered:\n" + "\n".join(f"    {f}" for f in trap_flags)

    stock_news_count = len(news_snippets)

    return f"""Target date: {target_date} ({target_date.strftime('%A')})

DOMINANT THEME DRIVING THIS PICK:
  Theme: {theme.theme_key}
  Direction: {theme.direction} (score {theme.direction_score:+.2f})
  Strength: {theme.strength:.3f}
  Articles: {theme.article_count} from {theme.source_count} sources
  Theme description: {theme.theme_label}
  Reasoning: {theme.representative_reasoning}
  Affected sectors: {theme.affected_sectors}

STOCK UNDER EVALUATION:
  Symbol: {candidate.symbol}
  Name: {candidate.name}
  Sector: {candidate.sector} ({"aligned with theme" if candidate.sector_aligned else "NOT directly in theme sectors"})
  Direct mentions in news: {candidate.direct_mention_count} article(s)
  Last close: ₹{candidate.last_close}
  Liquidity score: {candidate.liquidity_score:.2f} (0-1, higher = more liquid)
  20-day avg turnover: ₹{candidate.avg_turnover_cr_20d:.1f} crores

TECHNICAL SNAPSHOT:
{tech_block}

TECHNICAL CHART (indicators as of previous close):
{ta_summary or "  (not available)"}

FUNDAMENTALS (latest snapshot):
{fundamentals_summary or "  (not available)"}

RECENT STOCK-SPECIFIC NEWS (last 3 days, count = {stock_news_count}):
{news_block}

Reason carefully about whether this stock moves in the theme's direction on {target_date}. \
Apply all TRAP CHECKS from the core rules — especially if this stock:
  • Has already rallied recently (check return_5d_pct and return_20d_pct above)
  • Has low volume participation (check volume_ratio_20d)
  • Has no stock-specific news (stock_news_count = 0 → pure theme bet, weaker signal)

Your reasoning must explicitly state which (if any) TRAP CHECKS triggered and how they affected \
your final conviction number.

Respond with JSON:
{{
  "conviction": <1-10 integer>,
  "recommendation": "BUY" | "HOLD" | "AVOID",
  "primary_reasoning": "<1-2 sentence core thesis>",
  "supporting_factors": ["<bullet 1>", "<bullet 2>", ...],
  "key_risks": ["<risk 1>", "<risk 2>", ...],
  "alternative_scenario": "<what could go wrong or invalidate thesis>"
}}
"""


class StockReasoner:
    """Wraps Claude calls for per-stock reasoning."""

    def __init__(self, model_name: str | None = None):
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model_name = model_name or config.LLM_REASONING_MODEL

    def reason(
        self,
        candidate: StockCandidate,
        theme: ThemeAggregate,
        target_date: date,
    ) -> StockReasoning | None:
        news_snippets = _fetch_stock_news_snippets(candidate.stock_id, target_date)
        technicals = _fetch_technical_snapshot(candidate.stock_id, target_date)
        # Chart indicators (RSI, MACD, Bollinger, EMA, support/resistance)
        ta_snap = compute_ta_snapshot(candidate.stock_id, target_date)
        ta_summary = ta_snap.summary() if ta_snap else None
        # Valuation + quality (P/E, ROE, growth, D/E, 52w range)
        fund_summary = _fetch_fundamentals_summary(candidate.stock_id)

        prompt = _build_reasoning_prompt(
            candidate, theme, news_snippets, technicals, target_date,
            ta_summary=ta_summary,
            fundamentals_summary=fund_summary,
        )

        try:
            resp = self.client.messages.create(
                model=self.model_name,
                max_tokens=1024,
                system=REASONING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            logger.warning(
                "claude_api_error", symbol=candidate.symbol, error=str(e)[:200]
            )
            return None

        # Extract JSON from response
        raw = resp.content[0].text if resp.content else ""
        # Best-effort JSON extraction (sometimes Claude wraps in ```json ... ```)
        json_str = raw
        if "```" in raw:
            # Extract content between first ``` fences
            start = raw.find("```")
            if start >= 0:
                after = raw[start + 3 :]
                if after.startswith("json"):
                    after = after[4:]
                end = after.find("```")
                if end >= 0:
                    json_str = after[:end].strip()
                else:
                    json_str = after.strip()

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("claude_json_parse_failed", symbol=candidate.symbol, raw=raw[:200])
            return None

        tokens_in = resp.usage.input_tokens
        tokens_out = resp.usage.output_tokens
        cost_usd = tokens_in * CLAUDE_SONNET_INPUT_USD + tokens_out * CLAUDE_SONNET_OUTPUT_USD
        cost_inr = Decimal(str(round(cost_usd * USD_TO_INR, 6)))

        return StockReasoning(
            stock_id=candidate.stock_id,
            symbol=candidate.symbol,
            conviction=int(parsed.get("conviction", 5)),
            recommendation=str(parsed.get("recommendation", "HOLD")).upper(),
            primary_reasoning=str(parsed.get("primary_reasoning", ""))[:1500],
            supporting_factors=[str(x)[:300] for x in parsed.get("supporting_factors", [])][:6],
            key_risks=[str(x)[:300] for x in parsed.get("key_risks", [])][:6],
            alternative_scenario=str(parsed.get("alternative_scenario", ""))[:600],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_inr=cost_inr,
        )
