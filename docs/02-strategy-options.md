# Strategy Options & Selection

**Guiding principle**: simpler strategies with robust theoretical backing beat complex "predictive" models. Start simple, layer complexity only when simple works.

---

## Strategy universe (for retail, Indian markets)

### A. Systematic Momentum (recommended starting point)
**How it works**: Rank stocks by past N-month returns (commonly 3, 6, or 12 months). Long the top decile, hold M months, rebalance monthly. Simple version: long top 10 Nifty50 stocks by 3-month return, rebalance monthly.

**Why it works**: Well-documented behavioral factor (investors under-react to good news, over-react late). Backed by 40+ years of academic research.

**Pros**:
- Simple to implement
- Low turnover (monthly rebalance)
- Works in Indian markets (published research)
- Low brokerage/STT drag
- No leverage needed

**Cons**:
- Can have 20–30% drawdowns in regime changes
- Doesn't work in choppy, trendless markets
- Psychologically hard (buying at highs)

**Expected returns**: 15–25% annual over long horizons
**Capital needed**: ₹2L+ for meaningful position sizing

---

### B. Mean Reversion / Pair Trading
**How it works**: Find cointegrated stock pairs (e.g., HDFC Bank + ICICI Bank). When their spread deviates from historical mean, short the outperformer + long the underperformer. Profit when they converge.

**Why it works**: Similar businesses eventually trade similarly.

**Pros**:
- Market neutral (profit regardless of market direction)
- Statistical rigor
- Lower drawdowns than directional

**Cons**:
- Finding good pairs is hard
- Cointegration can break (structural changes)
- Higher brokerage (two legs)
- Requires short-selling (retail limited in India)

**Expected returns**: 10–20% annual
**Capital needed**: ₹5L+ (for margin on both legs)

---

### C. Options Selling (Theta Decay) — NOT for Year 1
**How it works**: Sell out-of-money options (usually credit spreads, iron condors) on Nifty/BankNifty. Collect premium, profit if option expires worthless.

**Why people like it**: Steady "income", high win rate (70–85%).

**Why DANGEROUS for beginners**:
- Looks like easy money until one bad day
- 2020 COVID, 2024 Nifty crashes = options sellers wiped accounts
- Requires deep understanding of Greeks, volatility regimes, tail risk
- Asymmetric payoff: small wins, huge losses

**Defer to Year 2 minimum. Read Natenberg + Taleb first.**

**Capital needed**: ₹3–5L minimum for proper position sizing

---

### D. Intraday Breakout (ORB — Opening Range Breakout)
**How it works**: First 15–30 min price range = "opening range". Breakout above = long, breakdown below = short. Exit by end of day.

**Pros**:
- No overnight risk
- Clear rules
- Works in trending markets

**Cons**:
- High frequency = high brokerage + slippage drag
- Requires active monitoring during market hours (conflict with day job!)
- Whipsaws in choppy days eat profits

**Not ideal for CTO with 10-7 job** — market hours conflict.

---

### E. Event-Driven / Earnings Plays
**How it works**: Trade around predictable events (earnings, ex-dividend, index inclusions).

**Pros**:
- Clear catalysts
- Lower frequency

**Cons**:
- Small edge after brokerage
- Requires careful information gathering
- Complex to backtest (not pure price-based)

---

### F. Factor Investing (Long-only equity)
**How it works**: Tilt portfolio toward known factors — quality, low-vol, value, momentum. Rebalance quarterly.

**Pros**:
- Works as a long-term wealth compounder
- Low time investment (quarterly)
- Tax-efficient (long-term capital gains in India if held >1 year)

**Cons**:
- Not "trading" — it's investing
- Slow to see results
- Feels like "just an index fund" early on

**Good option for baseline capital allocation** — pair with more active strategy.

---

## Decision matrix

| Strategy | Complexity | Time/week | Year-1 drawdown risk | Time-to-edge | Fit for day job |
|----------|-----------|-----------|---------------------|-------------|-----------------|
| A. Momentum | Low | 2–3 hr | Medium | High | ✅ Excellent |
| B. Pair trading | Medium | 5–7 hr | Low-Med | Medium | ✅ Good |
| C. Options sell | High | 10+ hr | **Very high** | Low | ⚠️ Defer |
| D. Intraday ORB | Medium | Market hrs | Medium | Medium | ❌ Conflicts |
| E. Event-driven | Medium | 3–5 hr | Medium | Medium | ⚠️ Ok |
| F. Factor investing | Low | 1 hr | Low | High | ✅ Excellent |

---

## Recommended approach

### Year 1
1. **Primary**: Strategy A (Systematic Momentum) on Nifty50/Nifty100
2. **Baseline**: Strategy F (Factor Investing) for majority of capital — stability
3. **Optional experiment**: Strategy B (Pair Trading) at small size, only after A is running

### Year 2+
- If A + B profitable, consider C (options selling) with small, defined-risk structures
- Gradually add complexity only as demonstrated competence builds

---

## Backtest requirements (before any strategy goes live)

Every strategy must clear:

1. **Minimum 5 years** of backtest data
2. **Out-of-sample test**: Train on years 1–4, test on year 5. Don't peek.
3. **Realistic transaction costs**: include STT (0.1% delivery), brokerage, stamp duty, GST, slippage (0.1%)
4. **Max drawdown** <25% (tolerable psychologically)
5. **Sharpe ratio** >1.0 (after costs)
6. **Positive returns in multiple regimes** (2008 crash, 2013 taper tantrum, 2018 midcap crash, 2020 COVID)
7. **Walk-forward test**: simulate "retraining" strategy over time

If backtest fails any of these → do not go live. Iterate.

---

## Open strategy decisions

- [ ] Primary strategy for Month 3 live paper: A (Momentum)
- [ ] Universe: Nifty50 only vs Nifty100 vs Nifty500
- [ ] Rebalance frequency: monthly vs weekly
- [ ] Position sizing: equal weight vs volatility weighted
