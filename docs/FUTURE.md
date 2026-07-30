# Future Enhancements

Organized roadmap for things to add LATER (not now). Each item has: **why**, **how**, **effort**, **priority**.

**Add to the system only when the current setup has proven itself for 30+ days and a specific metric needs improving.** Resist over-engineering.

---

## 🎯 Priority 1 — Only if rolling 30-day accuracy stays <55%

These are short-term-trading specific signals that could add real edge.

### 1.1 F&O Open Interest (OI) data
- **Why**: Shows where smart money is positioned. Large OI buildup at a strike = strong support/resistance. Moves stocks in 1-2 days (direct short-term edge).
- **How**:
  - NSE publishes daily OI data via `https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY` and per-stock endpoints
  - Fetch pre-market: PCR (put/call ratio), max pain, OI buildup
  - Add features: `oi_buildup_bullish`, `oi_buildup_bearish`, `pcr`, `max_pain_distance_pct`
  - Feed into Claude prompt for top candidates
- **Effort**: 4-6 hours (new ingestion module + DB table + features)
- **Cost**: Free (NSE public data)

### 1.2 FII/DII daily activity
- **Why**: Institutional flow is the single biggest short-term driver of Indian market direction. Big FII buying day = risk-on rotation; heavy selling = defensive plays outperform.
- **How**:
  - NSE publishes at `https://www.nseindia.com/api/fiidiiTradeReact` (daily ₹crores, cash + F&O)
  - Fetch post-market (available ~6 PM IST)
  - Add features: `fii_cash_net_cr`, `dii_cash_net_cr`, `fii_fo_net_cr`, 5d rolling sum
  - Feed into market_context aggregator
- **Effort**: 2 hours
- **Cost**: Free

### 1.3 Block/Bulk deals
- **Why**: When institutions do big block deals in a stock, follow-through is often 3-10 days. Real confirmation signal.
- **How**:
  - NSE block deals: `https://www.nseindia.com/api/block-deal`
  - Bulk deals similar endpoint
  - For each deal: stock, quantity, price, buyer/seller, side
  - Flag recent big deals per stock as bullish/bearish signal
- **Effort**: 2 hours
- **Cost**: Free

### 1.4 Intraday volume surge detector
- **Why**: Stocks with unusual volume intraday often continue trending. Catches momentum that hasn't hit pre-market yet.
- **How**: Modify `live_check.py` to also fetch intraday volume and compare to 20-day avg. Highlight stocks where current-volume / avg-20d > 2x.
- **Effort**: 1 hour
- **Cost**: Free (yfinance)

---

## 🔍 Priority 2 — If horizon expands from intraday → swing/position trading

### 2.1 Fundamental ratios (minimal set)
- **Why**: For holding periods > 1 week, fundamentals start to matter as safety filter (not primary driver).
- **How**:
  - Scrape `screener.in` for Nifty 100 stocks (respect rate limits — 1 req / 2s)
  - New table `stock_fundamentals`: `stock_id, quarter, pe, pb, roe, roce, debt_equity, promoter_pledge_pct, updated_at`
  - Update quarterly (after earnings season)
  - Add features: `roce`, `debt_equity`, `promoter_pledge_pct`, `pe_vs_5yr_avg`
- **Effort**: 4-6 hours
- **Cost**: Free (scraping)
- **Keep metrics minimal**: ROCE + D/E + promoter pledge + P/E catches 80% of value

### 2.2 Sector rotation indicator
- **Why**: Which sectors are leading vs lagging tells us where flow is going next.
- **How**:
  - Compute 20-day relative strength of each sector index vs Nifty 50
  - Top 3 sectors by RS get "rotation bonus" in scoring
  - Bottom 3 get "rotation penalty"
- **Effort**: 2 hours (we already have sector indices data)
- **Cost**: Free

---

## 📰 Priority 3 — More news sources (if pipeline is information-bottlenecked)

### 3.1 MarketAux paid news API
- **Why**: Pre-tagged entities, better coverage of Indian stocks than free RSS.
- **How**: Already implemented as optional in `.env.example`, just need to sign up and toggle `ENABLE_MARKETAUX=true`.
- **Effort**: 15 min
- **Cost**: $29/month (~₹2,400)
- **Benefit**: +20-30% news coverage

### 3.2 Reddit sentiment (r/IndianStockMarket, r/IndianStreetBets)
- **Why**: Retail sentiment is sometimes a leading indicator (or contrarian signal for tops).
- **How**:
  - Already scaffolded via `ENABLE_REDDIT` flag
  - Use PRAW to scrape daily top posts
  - Extract ticker mentions + sentiment
- **Effort**: 2-3 hours
- **Cost**: Free
- **Caveat**: High noise, mostly useful as contrarian signal

### 3.3 Twitter/X financial accounts
- **Why**: Breaking news and analyst tweets often hit X 30 min before news sites.
- **How**: API lockout post-2023 makes this expensive. Could scrape public accounts.
- **Effort**: 3-5 hours
- **Cost**: $100+/month (API) or scraping (grey area)
- **Skip unless desperate**

### 3.4 Earnings call transcripts
- **Why**: Management commentary > press release numbers. Tone shifts before numbers do.
- **How**: Trendlyne or Investor Relations pages of companies. Run through Gemini for sentiment extraction.
- **Effort**: 4-5 hours
- **Cost**: Free (scrape) or Trendlyne API (~₹500/month)

### 3.5 Historical news backfill
- **Why**: Would allow true historical backtest of news-driven pipeline.
- **How**:
  - NewsAPI.ai or EventRegistry: up to 1 year history
  - Backfill news for 6-12 months
  - Re-run theme extraction + fanout + Claude reasoning
  - Validate against actual 1-year returns
- **Effort**: 1 day (+ LLM rerun cost)
- **Cost**: $100-500 one-time for history, ₹5-10K LLM reprocessing
- **Best for**: Getting statistically significant accuracy read quickly

---

## 🧠 Priority 4 — ML/model improvements

### 4.1 Periodic retraining (monthly)
- **Why**: Market regimes change. Model trained on 2021-2024 data may not work in 2026.
- **How**:
  - Cron job 1st of every month: `python scripts/train_direction_model.py && python scripts/train_range_models.py`
  - Auto-deprecates old models, activates new
- **Effort**: 2 hours (write cron-safe version with error handling)

### 4.2 Multi-model ensemble
- **Why**: XGBoost vs LightGBM vs LogReg all tie at ~52% in our backtest. Averaging might beat any single one.
- **How**: Keep all 3 models trained, average their prob_up for ranking
- **Effort**: 3-4 hours
- **Expected gain**: 0.5-1.5pp accuracy

### 4.3 Better range regressor (two-output / volatility-scaled)
- **Why**: Current range model has weak correlation (0.07-0.23). Could improve by:
  - Using volatility regime (vol_regime feature) as conditional
  - Training separate models for high-vol vs low-vol regimes
  - Or using quantile regression for predicting bounds at specific percentiles
- **Effort**: 6-8 hours
- **Expected gain**: 20-30% tighter range predictions

### 4.4 LLM prompt auto-tuning (A/B test)
- **Why**: We hand-wrote the reasoning prompt. Systematic A/B could find better versions.
- **How**:
  - Keep multiple prompt variants
  - Randomly assign to each prediction
  - Track accuracy by prompt_version
  - Promote best performer monthly
- **Effort**: 4-6 hours
- **Expected gain**: 1-2pp on LLM-driven picks

### 4.5 Switch to local LLM for bulk NLP (cost)
- **Why**: If scaling to all 500+ Nifty 500 stocks, Gemini API cost might matter
- **How**: Ollama running Llama 3.1 70B locally (free after hardware)
- **Effort**: 1 day setup
- **Cost**: Zero after setup (needs decent GPU)

---

## 📱 Priority 5 — Product/UX enhancements

### 5.1 Telegram notifications
- **Why**: Get picks on phone at 8 AM automatically.
- **How**:
  - Create Telegram bot via BotFather
  - Add `send_telegram_summary()` to `daily_run.py`
  - Push top 10 trade setups as message
- **Effort**: 30 min
- **Cost**: Free

### 5.2 Daily run scheduler (launchd / cron)
- **Why**: Don't remember to run manually every morning.
- **How**:
  - macOS launchd plist: `~/Library/LaunchAgents/com.user.stockpredict.plist`
  - Triggers at 08:00 IST daily (weekdays only)
  - Runs `daily_run.py` then `live_check.py`
- **Effort**: 30 min
- **Cost**: Free

### 5.3 Web dashboard (Streamlit)
- **Why**: Quick mobile-friendly view of today's picks + rolling accuracy
- **How**:
  - `streamlit_app.py` reads predictions + validations from MySQL
  - Charts: daily accuracy, equity curve, source comparison
  - Deploy locally on `http://localhost:8501`
- **Effort**: 4-6 hours
- **Cost**: Free

### 5.4 Interactive live prompt mode
- **Why**: During market, ask system "should I hold INFY or exit?" with context
- **How**: CLI that takes stock + question, fetches live price + recent news, passes to Claude for reasoning
- **Effort**: 3-4 hours

---

## 🔧 Priority 6 — Ops / reliability

### 6.1 Automatic backups
- **Why**: DB corruption or accidental delete = lose all history
- **How**:
  - Cron job daily at 9 PM: `mysqldump stock_prediction > backups/YYYY-MM-DD.sql.gz`
  - Retain last 30 daily + 12 monthly
- **Effort**: 30 min
- **Cost**: Free

### 6.2 Cost tracking dashboard
- **Why**: Monitor LLM spend over time — catch runaway costs
- **How**: Query `api_costs` table daily, alert if > ₹50/day
- **Effort**: 1 hour

### 6.3 Error monitoring (Sentry or simple email)
- **Why**: If `daily_run.py` fails silently at 8 AM, don't find out at 3 PM
- **How**: Wrap entry point in try/except, email on failure (or Telegram)
- **Effort**: 1-2 hours

### 6.4 Reproducible training
- **Why**: Can recreate any past model exactly
- **How**: Pin seeds, save feature matrix snapshots, versioned training datasets in `data/training/`
- **Effort**: 2 hours

---

## 🧪 Priority 7 — Analysis / research improvements

### 7.1 Post-mortem automation
- **Why**: `analyze_day.py` shows misses but manual research is tedious
- **How**: For each miss, auto-Google the stock + fetch top 3 articles from post-market period. Pass to Gemini: "what caused this stock's +2% move that day?"
- **Effort**: 3-4 hours
- **Cost**: ₹1-2 per miss analysis

### 7.2 Pattern detection across days
- **Why**: Once we have 30+ days of misses, can find systematic failure modes
- **How**: Weekly job: cluster all misses by features (high 5d return, low volume, theme type). Surface top failure patterns.
- **Effort**: 4-5 hours

### 7.3 Confidence calibration
- **Why**: When system says "conviction 7/10", is it ACTUALLY right 70% of the time? Isotonic calibration fixes this.
- **How**: Train isotonic regression on (predicted_prob, actual_outcome) from validation history
- **Effort**: 2-3 hours

### 7.4 Counterfactual testing
- **Why**: What if we had changed rank 7-10 (weakest picks)? Would overall return improve?
- **How**: Backtest shows hypothetical "top 5 only" or "R:R > 2 only" filters
- **Effort**: 3-4 hours

---

## 📊 Priority 8 — Universe expansion (only after V1 proves itself)

### 8.1 Nifty 100 → Nifty 200
- **Why**: More opportunities, catches mid-cap themes
- **How**: `scripts/seed_nifty200.py`, backfill OHLCV for additional 100 stocks
- **Effort**: 2 hours (+ OHLCV backfill time)
- **Trade-off**: Need more careful liquidity filtering for smaller caps

### 8.2 Nifty 500
- **Why**: Full discovery potential
- **How**: Same as above but 500 stocks
- **Effort**: 4 hours
- **Note**: LLM reasoning cost scales linearly — would need to tighten candidate filter to ~30 before Claude

### 8.3 Sector-specific universes
- **Why**: Sometimes you want "only IT picks today" or "only pharma"
- **How**: Add `--sector` filter to `predict_today.py`
- **Effort**: 30 min

### 8.4 F&O universe (~200 stocks with derivatives)
- **Why**: Short-term traders often want F&O-enabled stocks (leverage, easier exit)
- **How**: NSE publishes F&O list; filter universe accordingly
- **Effort**: 2 hours

---

## 🌍 Priority 9 — Global diversification (much later)

### 9.1 US stocks
- **Why**: Different regime, sometimes Nifty-uncorrelated moves
- **How**: yfinance supports US tickers natively; sector taxonomy adapts
- **Effort**: 1 day

### 9.2 Crypto
- **Why**: 24/7 markets, different dynamics
- **How**: CoinGecko API for prices, different news sources
- **Effort**: 2-3 days
- **Note**: Completely different beast — treat as separate project

### 9.3 Commodities (gold, crude futures)
- **Why**: Macro hedges
- **How**: Already have some data (global_indices)
- **Effort**: 1 day

---

## 🔌 Priority 9.5 — Broker API integration (clarifying myths)

### Common misconception: "Let me add Groww/PhonePe/Paytm Money for better data"
**Reality**: These are B2C brokerage apps, not data providers. They:
- Don't have public APIs
- Don't predict stocks themselves
- Aggregate the SAME news RSS we already pull directly
- Show basic charts using standard indicators we already compute

**Adding Groww/PhonePe to our system = NO edge gain.** Skip.

### When broker integration actually helps
Only 2 scenarios:
1. **Real-time Level 2 data** — tick-by-tick quotes, order book depth (legit short-term edge)
2. **Auto-execution** — programmatically place orders (risky, needs SEBI-compliant setup)

### Brokers with public APIs

| Broker | API | Cost | Use case |
|--------|-----|------|---------|
| **Zerodha Kite Connect** ⭐ | Best documented | ₹2,000/mo | Full features: quotes, historical, execution, L2 order book |
| **Dhan** | Good, growing | Free tier + paid | Similar to Kite |
| **Upstox** | Good | Free | Similar |
| **AliceBlue ANT** | Basic | Free | Cheapest |
| **Groww** | ❌ No API | — | B2C only |
| **PhonePe / Paytm Money** | ❌ No API | — | B2C only |

### 9.5.1 Kite Connect WebSocket (tick-by-tick data)
- **Why**: Real-time quotes (yfinance is 15-min delayed at best). Live bid/ask depth reveals order flow direction.
- **How**: `kiteconnect` Python SDK, WebSocket ticker subscription
- **Effort**: 3-4 hours
- **Cost**: ₹2,000/mo (but includes historical + execution API)
- **Best for**: Short-term traders who want live intraday re-ranking (refresh picks every 15 min)

### 9.5.2 Auto-execution layer (LONG-TERM, only if system proves >55% accuracy)
- **Why**: Eliminate manual order entry — pick is produced, order is placed automatically at market open
- **How**:
  - Kite Connect order placement API
  - Safety rails: max position size, daily loss cap, emergency kill switch
  - Paper-trade 60 days first
- **Effort**: 2-3 weeks full implementation with risk controls
- **Cost**: ₹2,000/mo + capital
- **Risk**: HIGH — buggy code can lose real money. Requires:
  - Circuit breakers
  - Reconciliation logic (broker state vs our DB)
  - 100% test coverage
  - Gradual rollout (1 stock → 3 → 10)
- **Regulatory**: Personal use = legal. Managing others' money = SEBI RIA license required.

### 9.5.3 Portfolio integration (lightweight)
- **Why**: Track actual executed trades vs predictions. See which picks you actually took and real P&L.
- **How**:
  - Kite Connect read-only API pulls your positions + trades
  - Match against our predictions via (symbol, date)
  - Show: which picks did you take? Actual return vs predicted range?
- **Effort**: 4-6 hours
- **Cost**: ₹2,000/mo (if not already subscribed)
- **Good starting point** before full auto-execution

---

## 🎯 Priority 10 — Monetization / productization (when system proves profitable over 6+ months)

### 10.1 SaaS product
- **Risk**: Requires SEBI Registered Investment Advisor (RIA) license in India
- **Skip unless**: Willing to take regulatory path

### 10.2 Personal algo trading (execution layer)
- **Why**: Automate the execution of picks via Zerodha Kite Connect API
- **How**: Our old architecture doc (v1) had full design for this — revisit if moving from decision support → auto-trading
- **Effort**: 2-4 weeks full implementation
- **Risk**: Requires rigorous paper trading + risk rules before going live

### 10.3 Subscription newsletter (semi-manual)
- **Why**: Share picks + reasoning with friends/family for subscription
- **Legal risk**: Same SEBI issue — informational only, not advisory

---

## 📝 Usage notes

### When to reach for this file
1. **After 30 days of daily runs** — have data to decide which items to add
2. **When a specific metric underperforms** — pick targeted enhancement
3. **When horizon changes** — e.g., from intraday → swing → add fundamentals

### When NOT to add things
- Before 30 days of stable daily runs
- Without measuring current baseline
- All at once (one change → measure → next change)

### Decision framework for adding a feature
```
Cost:Time   ≤ 1 day of work?
Measurable: yes
Risk:       low (doesn't break daily_run.py)
Gain:       clear hypothesis (e.g., "F&O OI should add +2pp for F&O stocks")

If ALL four yes → add it
Otherwise → skip
```

### Anti-patterns to avoid
- ❌ "Let's add fundamentals because they sound important" (not for short-term)
- ❌ "Let's backfill 5 years of news" (₹30-50K cost, marginal value for forward-looking)
- ❌ "Let's add every feature from this file" (complexity kills clarity)
- ❌ Adding multiple features without measuring each separately

---

## 🗓️ Suggested order if everything else equal

If you're unsure where to start after 30 days:

1. **Telegram notifications + cron scheduler** (0.5 day, immediate QoL)
2. **FII/DII flow** (2 hours, real short-term signal)
3. **F&O OI data** (half day, most predictive for F&O stocks)
4. **Ensemble models** (half day, free accuracy bump)
5. **Historical news backfill** (1 day + ₹10K LLM cost, huge validation benefit)
6. Everything else — only if specific need arises

---

## Last updated
2026-04-23 — initial roadmap compiled based on Week 10 system state
