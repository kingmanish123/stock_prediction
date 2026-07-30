# Requirements Document — Pre-Market Stock Prediction System

**Version**: 1.0
**Last updated**: 2026-04-22
**Status**: Initial requirements baseline

This document defines **what the system must do** (functional), **how well it must do it** (non-functional), and **what it needs** (data, APIs, infra, dependencies) to operate.

Paired with [ARCHITECTURE.md](ARCHITECTURE.md) which defines **how** it does it.

---

## 1. Functional Requirements (FR)

Numbered for traceability. Each can be tested.

### Data ingestion
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1.1 | System SHALL fetch news from ≥5 Indian financial news sources per run | Must |
| FR-1.2 | System SHALL fetch global market indices (S&P, Nasdaq, Dow, Nikkei, Hang Seng, Gift Nifty) pre-market | Must |
| FR-1.3 | System SHALL fetch prior day OHLCV for all Nifty 50 stocks | Must |
| FR-1.4 | System SHALL fetch today's corporate events (earnings, results) | Must |
| FR-1.5 | System SHALL cache all raw data locally with timestamp | Must |
| FR-1.6 | System SHALL deduplicate news articles across sources | Must |
| FR-1.7 | System SHALL gracefully handle source failure (continue with remaining) | Must |

### NLP processing
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1 | System SHALL extract stock tickers mentioned in each article | Must |
| FR-2.2 | System SHALL compute sentiment score per article | Must |
| FR-2.3 | System SHALL classify event type (earnings, M&A, regulatory, other) | Must |
| FR-2.4 | System SHALL aggregate sentiment per stock per day | Must |
| FR-2.5 | System SHALL use LLM deep analysis for high-relevance articles only (cost control) | Should |

### Feature engineering
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-3.1 | System SHALL compute technical indicators (RSI, MACD, MA, ATR) per stock | Must |
| FR-3.2 | System SHALL compute momentum features (1d/5d/20d returns) | Must |
| FR-3.3 | System SHALL compute volume features (relative to 20d avg) | Must |
| FR-3.4 | System SHALL incorporate global market context features | Must |
| FR-3.5 | System SHALL incorporate calendar features (earnings day, F&O expiry) | Must |
| FR-3.6 | System SHALL find k-nearest historical days for pattern matching | Should |

### Prediction
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-4.1 | System SHALL predict UP/DOWN direction for all Nifty 50 stocks | Must |
| FR-4.2 | System SHALL predict intraday price range (low–high) per stock | Must |
| FR-4.3 | System SHALL output a calibrated confidence score (0-100%) per prediction | Must |
| FR-4.4 | System SHALL produce LLM-based reasoning for top-ranked predictions | Should |
| FR-4.5 | System SHALL rank top 5 BUY and top 5 SELL/AVOID candidates | Must |

### Output
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-5.1 | System SHALL print a human-readable report to terminal | Must |
| FR-5.2 | System SHALL save a Markdown report per day | Must |
| FR-5.3 | System SHALL save a JSON predictions file per day | Must |
| FR-5.4 | System SHALL display rolling 30-day accuracy in each report | Must |
| FR-5.5 | System MAY push summary to Telegram if configured | May |

### Validation
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-6.1 | System SHALL fetch actual OHLCV post-market | Must |
| FR-6.2 | System SHALL compute direction accuracy per prediction | Must |
| FR-6.3 | System SHALL compute range accuracy per prediction | Must |
| FR-6.4 | System SHALL compute top-5 hit rate | Must |
| FR-6.5 | System SHALL persist validation results immutably | Must |
| FR-6.6 | System SHALL update rolling 30-day accuracy metrics | Must |

### Experimentation
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-7.1 | Features SHALL be modular (easy to add/remove individually) | Must |
| FR-7.2 | Models SHALL be swappable (plug in LightGBM instead of XGBoost without refactor) | Must |
| FR-7.3 | System SHALL support backtesting on historical data with configurable date range | Must |
| FR-7.4 | System SHALL version models (trained artifacts + hyperparameters logged) | Must |

### Operations
| ID | Requirement | Priority |
|----|-------------|----------|
| FR-8.1 | System SHALL be runnable via single command: `python main.py` | Must |
| FR-8.2 | System SHALL be runnable via single command: `python validate.py` | Must |
| FR-8.3 | System SHALL log all runs with duration, status, errors | Must |
| FR-8.4 | System SHALL support `--date` flag to re-run for past date (if data still available) | Should |
| FR-8.5 | System SHALL support `--dry-run` flag (no external calls, use cache) | Should |

---

## 2. Non-Functional Requirements (NFR)

### Performance
- **NFR-P1**: Pre-market run SHALL complete in <5 minutes under normal conditions
- **NFR-P2**: Backtest on 1 year of historical data SHALL complete in <30 minutes on M1/M2 Mac
- **NFR-P3**: News ingestion (all sources) SHALL complete in <60 seconds using parallel fetches

### Reliability
- **NFR-R1**: Any single data source failure SHALL NOT cause total run failure (graceful degradation)
- **NFR-R2**: System SHALL retry transient API errors up to 3 times with exponential backoff
- **NFR-R3**: System SHALL continue functioning with degraded accuracy if any one feature category fails

### Portability
- **NFR-Po1**: System SHALL run on macOS (primary) and Linux (secondary)
- **NFR-Po2**: System SHALL NOT require any cloud account or VPS
- **NFR-Po3**: System SHALL NOT require sudo/root privileges

### Maintainability
- **NFR-M1**: Each stage (ingest/nlp/features/model/report) SHALL be independently testable
- **NFR-M2**: Adding a new news source SHALL require changes to only 1 new file + config edit
- **NFR-M3**: Changing a model hyperparameter SHALL require only YAML edit (no code change)
- **NFR-M4**: Code coverage SHALL be ≥60% for critical paths (ingest, features, models)

### Security
- **NFR-S1**: API keys SHALL be stored in `.env` file (gitignored)
- **NFR-S2**: No credentials SHALL appear in logs
- **NFR-S3**: Data directory SHALL be gitignored (prevent accidental commit of scraped content)

### Observability
- **NFR-O1**: All API calls SHALL be logged with duration + status
- **NFR-O2**: Run summary SHALL include cost spend (LLM + paid APIs)
- **NFR-O3**: Error logs SHALL include full context (stack trace + run state)

### Honesty (project-specific)
- **NFR-H1**: Validation results SHALL be immutable (append-only)
- **NFR-H2**: Backtest SHALL use proper time-series cross-validation (no look-ahead)
- **NFR-H3**: System SHALL NOT display predictions without showing rolling accuracy

---

## 3. Data Requirements (DR)

### Historical data
| ID | Data | Required Depth | Source | Cost |
|----|------|----------------|--------|------|
| DR-1.1 | Nifty 50 OHLCV daily | 5 years minimum | yfinance | Free |
| DR-1.2 | Nifty 50 intraday 5-min | 2 years (optional, Phase 3+) | nsepy / paid | Free–₹2K/mo |
| DR-1.3 | Nifty 50 constituents over time | 5 years | NSE indices history | Free (scrape) |
| DR-1.4 | Global indices daily | 5 years | yfinance | Free |
| DR-1.5 | Corporate actions (splits/bonuses) | 5 years | yfinance / NSE | Free |
| DR-1.6 | Corporate events calendar | Current week | NSE / BSE | Free (scrape) |

### Live/near-live data (per daily run)
| ID | Data | Timing | Source | Cost |
|----|------|--------|--------|------|
| DR-2.1 | Overnight news (India + global) | Last 18–24 hr | RSS + APIs | See section 4 |
| DR-2.2 | Global markets close | US/Asia close | yfinance | Free |
| DR-2.3 | Gift Nifty pre-market | 6:00–8:00 AM IST | yfinance / investing.com scrape | Free |
| DR-2.4 | Today's corporate events | Current day | NSE / BSE | Free |

### Storage estimates
| Data type | Size |
|-----------|------|
| 5 years OHLCV (50 stocks) | ~50 MB |
| News archive (1 year, all sources) | ~500 MB |
| Feature snapshots (daily × 1 year) | ~50 MB |
| Trained models | ~5 MB |
| Validation history | <10 MB |
| **Total estimated** | **~620 MB → 1 GB buffer** |

---

## 4. API Requirements (detailed)

This is the most important section for your budget + setup. Tiered recommendations.

### 4.1 News APIs

#### Tier 1 — Free (V1 baseline)

| API | What it provides | Signup | Notes |
|-----|------------------|--------|-------|
| **NSE Corporate Announcements** | Official company filings (most authoritative) | None (public JSON endpoints) | Critical for earnings/results/regulatory. Scrape: `nseindia.com/api/corporate-announcements` |
| **BSE Corporate Announcements** | Official BSE filings | None | Similar to NSE but some mid/small caps listed here only |
| **MoneyControl RSS** | General market news, stock-specific | None | Multiple RSS feeds for different categories |
| **Economic Times Markets RSS** | Business + markets | None | High-quality editorial |
| **LiveMint Markets RSS** | Markets news | None | Decent coverage |
| **Business Standard RSS** | Business news | None | Additional source |
| **Yahoo Finance (via yfinance)** | Per-ticker news | None (built into yfinance) | `ticker.news` returns recent items |
| **Reddit r/IndianStreetBets / r/IndianStockMarket** | Retail sentiment (high noise) | Free Reddit dev account | Useful as contrarian indicator |
| **Twitter/X Free Tier** | Limited (no search) | Free | Mostly useless after API lockdown |

**V1 strategy**: NSE + BSE + 4 RSS sources + yfinance news. Zero cost. Should give 40–80 articles/day.

#### Tier 2 — Paid, affordable (V2 upgrade — if V1 needs more signal)

| API | Cost/month | What it adds | Recommended? |
|-----|-----------|--------------|--------------|
| **MarketAux** | ~$29 (~₹2,400) | Financial-specific news aggregation, tickers pre-tagged | ⭐ **Top pick** — cheap, purpose-built |
| **NewsData.io** | $29–99 (~₹2,400–8,000) | Multi-source aggregator incl. Indian sources | Good alternative |
| **GNews API** | $49–99 (~₹4,000–8,000) | Google News API (broad) | Broad, less finance-focused |
| **NewsAPI.org** | $449 (business) | Broad news | Too expensive for V2 |
| **Finnhub** | $50 (~₹4,100) | Company news (includes BSE/NSE), press releases | Decent, US-focused |

**V2 recommendation**: Add **MarketAux** ($29/mo ≈ ₹2,400) — best value for financial news aggregation with pre-tagged entities.

#### Tier 3 — Premium (only if V2 shows strong results)

- **NewsAPI.ai / Event Registry**: $100–500/mo. Deep analytics, entity linking, topic clustering. Consider at Month 6+ only if system is profitable/valuable.
- Bloomberg / Refinitiv: NOT recommended. $2K+/month, enterprise-only.

#### Recommended progression
- **Month 1–2**: Tier 1 only (free)
- **Month 3–4**: Add MarketAux if V1 direction accuracy is <55%
- **Month 6+**: Evaluate Tier 3 only if system is demonstrably profitable + tool is being used

---

### 4.2 Market Data APIs

| API | What it provides | Cost | Verdict |
|-----|------------------|------|---------|
| **yfinance** (Python lib) | EOD OHLCV for NSE stocks (`.NS` suffix), global indices, news | Free | ⭐ **Primary** — reliable, maintained |
| **nsepy** | NSE-specific data, indices, futures/options | Free | Secondary, good for intraday/F&O if needed |
| **nsetools** | NSE wrapper | Free | Alternative to nsepy |
| **Alpha Vantage** | Free tier 25 req/day; paid $49.99/mo | Free tier limited | Not needed — yfinance covers it |
| **Zerodha Kite Historical** | Intraday data (1-min/5-min) | ₹2,000/mo | Only needed if doing intraday, which Phase 1 doesn't |
| **EOD Historical Data** | India EOD data | $19.99/mo | Optional backup |

**Recommendation**: yfinance + nsepy (both free) — sufficient for entire Phase 1–2.

---

### 4.3 Economic Calendar / Events

| API | What it provides | Cost |
|-----|------------------|------|
| **NSE Events Calendar** | Earnings, results dates | Free (scrape) |
| **BSE Events Calendar** | Same for BSE | Free (scrape) |
| **Trading Economics** | Macro events (RBI meetings, GDP, CPI) | Free tier + paid |
| **Investing.com Economic Calendar** | Global macro events | Free (scrape) |

**Recommendation**: Scrape NSE + Investing.com = sufficient.

---

### 4.4 LLM API

| Provider | Cost | Verdict |
|----------|------|---------|
| **Anthropic Claude** | ~$3/M input, $15/M output (Sonnet) | Recommended if user coupon is Claude |
| **OpenAI GPT-4o** | Similar pricing | Acceptable if user coupon is OpenAI |
| **OpenRouter** | Pass-through, unified | Good for experimentation across models |
| **Together.ai / Groq** | Open-source models (Llama), cheaper | Backup if main provider down |
| **Local Llama 3 8B** (via Ollama) | Free (uses your GPU/CPU) | Fallback; lower quality but zero cost |

**Daily cost estimate**: With ~15 deep LLM calls per run (top articles + top predictions), ~₹10–15 per run, ~₹200–300/month. Covered by user's coupon.

**Question**: Which LLM coupon do you have? (Claude / OpenAI / other?) Answer affects final implementation.

---

### 4.5 Optional: Telegram Bot (for phone push)

| Service | Cost |
|---------|------|
| Telegram Bot API | Free |
| Setup effort | 15 minutes (create bot via BotFather, save token) |

Optional but low-cost — lets you get the daily report on your phone.

---

## 5. Tech Stack Requirements

### 5.1 Runtime environment

| Requirement | Specification |
|-------------|---------------|
| OS | macOS 13+ (primary) / Linux Ubuntu 22+ (secondary) |
| Python | 3.11+ |
| Disk | 5 GB free (data + models + venv) |
| RAM | 8 GB minimum, 16 GB recommended (for FinBERT local inference) |
| GPU | Not required (optional: speeds up FinBERT) |
| Network | Stable broadband (during 8 AM run) |

### 5.2 Python dependencies

**Core libraries** (install via poetry/uv):
```toml
[tool.poetry.dependencies]
python = "^3.11"

# Data
pandas = "^2.2"
numpy = "^2.1"
pyarrow = "^18.0"           # Parquet I/O
yfinance = "^0.2.49"
nsepy = "^0.8"              # NSE-specific (or nsetools)
requests = "^2.32"
httpx = "^0.28"             # async HTTP
beautifulsoup4 = "^4.12"    # HTML scraping
feedparser = "^6.0"         # RSS parsing

# NLP
sentence-transformers = "^3.3"    # for deduplication
transformers = "^4.47"            # FinBERT
torch = "^2.5"                    # transformers backend
spacy = "^3.8"                    # optional NER

# Anthropic / LLM
anthropic = "^0.42"               # Claude SDK
# OR
openai = "^1.60"                  # if OpenAI

# ML
scikit-learn = "^1.6"
xgboost = "^2.1"
lightgbm = "^4.5"                 # alternative
ta = "^0.11"                       # technical indicators

# Output
rich = "^13.9"                    # beautiful terminal output
tabulate = "^0.9"

# Database
sqlalchemy = "^2.0"
# sqlite3 (built in)

# Config / utilities
pyyaml = "^6.0"
python-dotenv = "^1.0"
pydantic = "^2.10"
tenacity = "^9.0"                 # retry logic
click = "^8.1"                    # CLI

# Logging
structlog = "^24.4"

# Telegram (optional)
python-telegram-bot = "^21.8"

# Notebooks
jupyterlab = "^4.3"
matplotlib = "^3.10"
seaborn = "^0.13"
plotly = "^5.24"

[tool.poetry.group.dev.dependencies]
pytest = "^8.3"
pytest-cov = "^6.0"
ruff = "^0.8"                     # lint + format
mypy = "^1.13"
```

### 5.3 System tools

- Git
- `uv` or `poetry` for dependency management (uv preferred — 10x faster)
- `make` (optional — for convenient run targets)
- Docker (optional — only if you want containerized DB later)

---

## 6. Secrets / Environment Variables

`.env.example` template:
```
# LLM
ANTHROPIC_API_KEY=your-claude-key
# or
OPENAI_API_KEY=your-openai-key

# Optional paid news APIs
MARKETAUX_API_KEY=
NEWSDATA_IO_API_KEY=

# Optional Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Configuration
LLM_PROVIDER=anthropic      # 'anthropic' or 'openai'
LLM_MODEL=claude-opus-4-7   # or claude-sonnet-4-6 for cheaper
LOG_LEVEL=INFO
DATA_DIR=./data
REPORTS_DIR=./reports
```

---

## 7. Operational Requirements

### 7.1 Commands user will run

| Command | Purpose | When |
|---------|---------|------|
| `python main.py` | Run pre-market pipeline + generate today's report | 8 AM IST daily |
| `python validate.py` | Fetch actuals + compute accuracy for today | 4 PM IST daily (or any time post-close) |
| `python validate.py --date 2026-04-21` | Validate historical date | On demand |
| `python scripts/train_models.py` | Retrain models on latest data | Weekly (Sunday) |
| `python scripts/backtest.py --from 2025-01-01 --to 2025-12-31` | Run historical backtest | On demand |
| `python scripts/daily_data_pull.py` | Pre-cache data for tomorrow's run | Evening (optional) |

### 7.2 Automation (optional, not required)

User explicitly said "manually 8 baje script run karunga". But if later desired:
- macOS `launchd` plist for auto-start at 8 AM
- Or simple `cron` entry:
  ```
  0 8 * * 1-5 cd /path/to/algo-trading-system && /usr/local/bin/python main.py
  0 16 * * 1-5 cd /path/to/algo-trading-system && /usr/local/bin/python validate.py
  ```

### 7.3 Backup

- Data directory (predictions, validations) backed up weekly to user's iCloud/Dropbox
- SQLite DB auto-dumped weekly to `backups/YYYY-MM-DD.sql.gz`

---

## 8. Constraints

- **C-1**: No live trading or broker integration (out of scope)
- **C-2**: No cloud hosting (100% local execution)
- **C-3**: No multi-user — single user only
- **C-4**: Indian markets (NSE) only in Phase 1
- **C-5**: Nifty 50 universe only in Phase 1 (Nifty 100 from Phase 2 if Phase 1 succeeds)
- **C-6**: Daily granularity only in Phase 1 (intraday from Phase 3 if needed)
- **C-7**: English news only in Phase 1 (Hindi news optional future expansion)

---

## 9. Success Metrics (quantitative)

### System-level (NFR)
- Pre-market run completes in <5 minutes 95% of days
- Zero data loss incidents
- Zero credential leaks

### Prediction accuracy (primary success — user's criterion)
- **Direction accuracy** ≥ 60% (rolling 30-day)
- **Top-5 BUY hit rate** ≥ 3 out of 5 average (rolling 30-day)
- **Range hit rate** ≥ 40% (harder — actual high/low within predicted range)

### Measured over
- Minimum 60 trading days (≈ 3 months) before evaluation
- Must pass on held-out data, not training data

---

## 10. Open Items / Assumptions

### Questions for user (clarify before Phase 1 starts)

1. **LLM provider**: Claude or OpenAI coupon? (Affects SDK choice)
2. **Telegram integration**: Do you want phone push? Low effort, optional.
3. **Historical data depth**: 5 years OK, or prefer longer (10 years)? (Longer = more regimes, but older data less representative)
4. **Folder rename**: Should `algo-trading-system/` be renamed to `stock-prediction-system/`? (Matches new scope but requires path updates in docs)
5. **Project 2 (Videos) parallel timing**: Do we start videos now in parallel, or focus 100% on this until Month 3 validation gate?

### Assumptions documented

- User's Mac has 8+ GB RAM (FinBERT needs ~2 GB at inference)
- User is comfortable running Python scripts from terminal
- User has Git installed locally
- User's internet is reliable enough for 8 AM runs
- User will NOT trade based on Phase 1 predictions until backtest + 60 days of paper validation shows edge
- User's LLM coupon covers ~₹2,000–3,000/month of usage

### Risks flagged

- **Data quality risk**: free news sources may be incomplete vs paid; accept as baseline, measure
- **Regime risk**: model trained on 2020–2024 may fail in new regime (e.g., war, pandemic)
- **Overfitting risk**: user as CTO will want to tweak; enforce experiment framework discipline
- **Sunk-cost fallacy**: if system doesn't hit 60% after 3 months, commit to honest pivot, don't keep tweaking

---

## 11. Out of Scope (explicit)

To prevent scope creep, these are explicitly NOT in this project:

- ❌ Automated trading / broker integration
- ❌ Real-time predictions (intraday streaming)
- ❌ Options pricing / Greek analysis
- ❌ Portfolio optimization / allocation
- ❌ Tax calculations / reporting
- ❌ Social features (sharing, leaderboards)
- ❌ Mobile app / native UI
- ❌ Selling predictions to others (would require SEBI RIA license)
- ❌ Crypto markets
- ❌ Non-Indian markets

Future phases may revisit some of these (never the SEBI-regulated ones).

---

## 12. Acceptance Criteria for V1 Complete

System is V1-complete when:

- [ ] `python main.py` runs end-to-end without manual intervention
- [ ] Daily report generated in <5 min with all sections populated
- [ ] `python validate.py` produces accuracy metrics
- [ ] Historical backtest shows ≥58% direction accuracy on held-out 2025 data
- [ ] Rolling 30-day accuracy displayed in every report
- [ ] At least 30 consecutive days of successful daily runs logged
- [ ] README.md has quickstart instructions
- [ ] All free-tier news sources integrated
- [ ] LLM integration working with usage tracking
- [ ] Tests cover critical paths (ingestion, features, prediction)
