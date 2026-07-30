# System Architecture — Pre-Market Stock Prediction System

**Version**: 2.0 (pivoted from trading-execution to pure prediction)
**Last updated**: 2026-04-22
**Status**: Design phase
**Project note**: Folder name `algo-trading-system/` is historical; actual scope is a **prediction-only analytics tool**.

---

## 1. System Overview

### Purpose
A **local, pre-market, data-driven stock prediction system** that runs before market open, ingests overnight + global news + historical market data, and outputs a ranked list of Nifty 50 stocks with:
- Predicted direction (UP / DOWN / FLAT)
- Predicted intraday range (high / low)
- Confidence score per prediction
- Reasoning (which news/signals drove the call)

### What it is
- A **decision support tool** — user reads predictions, decides manually
- A **research platform** — experiment with features, models, news sources
- A **learning engine** — tracks its own accuracy over time, improves iteratively

### What it is NOT
- ❌ Not a trading bot (no broker integration, no orders, no capital at risk)
- ❌ Not a crystal ball (no "exact price at 2:35 PM" predictions)
- ❌ Not a SaaS/product (personal use only — no UI, no users, no SEBI advisory issues)
- ❌ Not cloud-hosted (100% local execution)

### Core principles

1. **Data-only, no discretion** — every prediction is derived from data + model, not hunches
2. **Local-first** — runs on user's Mac, no VPS needed
3. **Pre-market batch** — one daily run at 8 AM IST, not realtime
4. **Experiment-friendly** — easy to swap features, models, data sources (CTO wants to iterate)
5. **Track honestly** — log every prediction + outcome; measure edge empirically
6. **Read-only** — never places trades, never needs trading credentials

### Validation criteria (from user)
- **Primary**: 60%+ directional accuracy on Nifty 50 daily predictions
- **Secondary**: 2–3 of top 5 daily picks showing positive returns

---

## 2. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                  DAILY SCHEDULE (IST)                              │
│                                                                    │
│  08:00  → Pre-market run (full pipeline)   — predictions output   │
│  09:15  → Market opens (no action by system)                      │
│  15:30  → Market closes (no action by system)                     │
│  16:00  → Post-market validation run       — accuracy logged      │
│  Sunday → Weekly review + retraining (optional)                   │
└────────────────────────────────────────────────────────────────────┘


┌──────────────────── PRE-MARKET PIPELINE (8:00 AM) ─────────────────────┐
│                                                                        │
│  ┌───────────────────┐                                                │
│  │  User runs:       │                                                │
│  │  $ python main.py │                                                │
│  └─────────┬─────────┘                                                │
│            ▼                                                          │
│  ┌──────────────────────────────────────────────────────┐            │
│  │ STAGE 1: DATA INGESTION                              │            │
│  │  ├─ News Collector (APIs + RSS)                      │            │
│  │  ├─ Market Data Collector (yfinance + nsepy)         │            │
│  │  ├─ Global Indices (S&P, Nasdaq, Nikkei, Hang Seng) │            │
│  │  ├─ Gift Nifty / SGX Nifty (pre-market indicator)    │            │
│  │  └─ Corporate Events (earnings, results calendar)    │            │
│  └─────────┬────────────────────────────────────────────┘            │
│            ▼                                                          │
│  ┌──────────────────────────────────────────────────────┐            │
│  │ STAGE 2: NLP / SENTIMENT PROCESSING                  │            │
│  │  ├─ News deduplication + clustering                  │            │
│  │  ├─ Entity extraction (which stock is this about?)   │            │
│  │  ├─ Sentiment scoring (FinBERT + LLM combo)          │            │
│  │  ├─ Event classification (earnings, M&A, regulatory) │            │
│  │  └─ Impact magnitude estimation                      │            │
│  └─────────┬────────────────────────────────────────────┘            │
│            ▼                                                          │
│  ┌──────────────────────────────────────────────────────┐            │
│  │ STAGE 3: FEATURE ENGINEERING (per stock in Nifty 50) │            │
│  │  ├─ News features (sentiment, volume, event_type)    │            │
│  │  ├─ Technical features (RSI, MACD, MA, volatility)   │            │
│  │  ├─ Momentum (1d, 5d, 20d returns)                   │            │
│  │  ├─ Volume features (relative to avg)                │            │
│  │  ├─ Market context (Gift Nifty, global sentiment)    │            │
│  │  ├─ Calendar features (earnings day? expiry?)        │            │
│  │  └─ Historical similarity (k-NN to past days)        │            │
│  └─────────┬────────────────────────────────────────────┘            │
│            ▼                                                          │
│  ┌──────────────────────────────────────────────────────┐            │
│  │ STAGE 4: PREDICTION ENGINE (ensemble)                │            │
│  │  ├─ Model A: Direction Classifier   (XGBoost)        │            │
│  │  ├─ Model B: Range Regressor        (XGBoost)        │            │
│  │  ├─ Model C: LLM Reasoning Layer    (Claude)         │            │
│  │  ├─ Ensemble voter (weighted by past accuracy)       │            │
│  │  └─ Confidence calibration                           │            │
│  └─────────┬────────────────────────────────────────────┘            │
│            ▼                                                          │
│  ┌──────────────────────────────────────────────────────┐            │
│  │ STAGE 5: REPORT GENERATION                           │            │
│  │  ├─ Top 5 BUY candidates + ranges + confidence       │            │
│  │  ├─ Top 5 SELL/AVOID candidates                      │            │
│  │  ├─ Key news drivers per stock                       │            │
│  │  ├─ Overall market bias (bullish/bearish/neutral)    │            │
│  │  └─ Rolling accuracy history (last 30 days)          │            │
│  └─────────┬────────────────────────────────────────────┘            │
│            ▼                                                          │
│  ┌──────────────────────────────────────────────────────┐            │
│  │ STAGE 6: OUTPUT                                      │            │
│  │  ├─ Rich terminal output (colored tables via Rich)   │            │
│  │  ├─ Markdown report: reports/YYYY-MM-DD.md           │            │
│  │  ├─ JSON for machine use: predictions/YYYY-MM-DD.json│            │
│  │  └─ (optional) Telegram push to phone                │            │
│  └──────────────────────────────────────────────────────┘            │
└────────────────────────────────────────────────────────────────────────┘


┌──────────────── POST-MARKET VALIDATION (4:00 PM) ──────────────────────┐
│                                                                        │
│  ┌──────────────────────────────────────────────────────┐            │
│  │ STAGE 7: VALIDATION                                  │            │
│  │  ├─ Fetch today's actual OHLCV for Nifty 50          │            │
│  │  ├─ Compare prediction vs actual per stock           │            │
│  │  │   ├─ Direction correct? (binary)                  │            │
│  │  │   ├─ Actual in predicted range? (binary)          │            │
│  │  │   └─ Top-5 accuracy (how many of 5 positive?)     │            │
│  │  ├─ Append to results DB                             │            │
│  │  └─ Print daily validation summary                   │            │
│  └──────────────────────────────────────────────────────┘            │
└────────────────────────────────────────────────────────────────────────┘


┌──────────────── ALL COMPUTATION IS LOCAL ──────────────────────────────┐
│                                                                        │
│  User's Mac                                                           │
│    ├─ SQLite DB (predictions, validations, metrics)                   │
│    ├─ Parquet files (news + market data cache)                        │
│    ├─ Models dir (trained XGBoost pickles)                            │
│    ├─ Logs dir (per-run JSON logs)                                    │
│    └─ Reports dir (daily markdown + JSON)                             │
│                                                                        │
│  External calls ONLY for:                                             │
│    ├─ News APIs (HTTP GET)                                            │
│    ├─ Market data (yfinance, nsepy)                                   │
│    └─ Claude LLM API (prediction reasoning layer)                     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Stage-by-Stage Detail

### Stage 1 — Data Ingestion

**Responsibility**: Collect everything needed for today's predictions.

#### Sub-components

**1.1 News Collector**
- Pulls overnight news (last 18–24 hours) from multiple sources
- Sources (tiered — see [REQUIREMENTS.md](REQUIREMENTS.md) for full API details):
  - **Free tier (always on)**:
    - NSE/BSE corporate announcements (official, most authoritative)
    - MoneyControl, Economic Times, LiveMint (RSS feeds)
    - Yahoo Finance news (via yfinance)
  - **Paid tier (if budget allows)**:
    - MarketAux or NewsData.io for aggregated Indian stock news
- Deduplication: fuzzy-match titles + URL normalization
- Storage: `data/news/YYYY-MM-DD/<source>.json`

**1.2 Market Data Collector**
- Previous day's OHLCV for all Nifty 50 stocks
- Trailing 250 days of OHLCV (for technical indicators)
- Global indices close: S&P 500, Nasdaq, Dow, Nikkei, Hang Seng, DAX
- Gift Nifty (SGX Nifty) — most reliable pre-market India indicator
- Source: `yfinance` (free, handles `.NS` tickers)
- Storage: Parquet files in `data/market/`

**1.3 Corporate Events Collector**
- Today's scheduled earnings / results (NSE website scrape)
- F&O expiry flags
- Dividend / bonus ex-dates
- Storage: `data/events/YYYY-MM-DD.json`

**Output of Stage 1**: all raw data cached locally, timestamped.

---

### Stage 2 — NLP / Sentiment Processing

**Responsibility**: Turn unstructured text into structured signals.

#### Sub-components

**2.1 Deduplication & Clustering**
- Same news often appears in multiple sources
- Use `sentence-transformers` embeddings → cosine similarity > 0.85 = duplicate
- Cluster → pick canonical version
- Reduces 500+ articles to ~100–150 unique stories

**2.2 Entity Extraction**
- Extract company names, tickers, sectors from news text
- Approach: rule-based matcher against Nifty 50 stock list + aliases (e.g., "RIL" → RELIANCE)
- Optional: spaCy NER for broader coverage
- Output: `article_id → [stock_tickers_affected]`

**2.3 Sentiment Scoring (hybrid)**
- **Fast layer**: FinBERT (free, local) runs on every article
  - Output: positive / negative / neutral + score
- **Deep layer**: Claude LLM for top-N important stories
  - Input: article text + ticker context
  - Output: structured JSON with sentiment (-5 to +5), event type, confidence, expected price impact direction + magnitude
- Cost control: LLM only runs on articles flagged as high-relevance (by FinBERT + entity count)

**2.4 Event Classification**
- Classes: earnings_result, guidance, M&A, regulatory, management_change, credit_rating, macro, product_launch, analyst_rating, other
- Approach: keyword rules + LLM classifier for ambiguous cases
- Stored as feature vector

**2.5 Impact Magnitude Estimation**
- Historical lookup: similar event types → typical price move
- e.g., "earnings beat by >10%" → historical avg +2.5% same-day
- Feature: `expected_magnitude_from_history`

**Output of Stage 2**: `news_signals` table, one row per (stock, date) with aggregated sentiment + event features.

---

### Stage 3 — Feature Engineering

**Responsibility**: Assemble the feature vector for each stock for today.

Per stock (Nifty 50 × 1 row = 50 rows):

| Feature Category | Examples |
|------------------|----------|
| **News features** | `sentiment_avg`, `sentiment_max`, `article_count`, `high_impact_event_flag`, `event_type_earnings`, `llm_expected_direction` |
| **Technical** | `rsi_14`, `macd_signal`, `sma_20_vs_sma_50`, `bollinger_position`, `atr_14` |
| **Momentum** | `return_1d`, `return_5d`, `return_20d`, `relative_strength_vs_nifty` |
| **Volume** | `volume_ratio_vs_20d_avg`, `dollar_volume` |
| **Volatility** | `realized_vol_20d`, `vol_regime` (low/normal/high) |
| **Market context** | `gift_nifty_return`, `sp500_return`, `dxy_return`, `crude_return` (global) |
| **Calendar** | `is_earnings_day`, `is_expiry`, `day_of_week`, `days_to_earnings` |
| **Historical similarity** | `k_nearest_similar_days` — find top 10 historical days with similar feature profile → average return |

**Output of Stage 3**: `features.parquet` for today — 50 rows × ~40 columns.

---

### Stage 4 — Prediction Engine

**Responsibility**: Turn features into predictions.

#### Model ensemble

**Model A — Direction Classifier (XGBoost)**
- Target: `today's close > today's open ?` (binary)
- Training: 5 years of historical (same features, same universe)
- Output: probability of UP for each stock
- Why XGBoost: handles mixed features well, fast, interpretable (SHAP values)

**Model B — Range Regressor (XGBoost)**
- Target: today's `(high - low) / open` — predicts daily range as % of open
- Combined with ATR/volatility → predicted high/low bands
- Output: predicted `(low, high)` range per stock

**Model C — LLM Reasoning Layer (Claude)**
- Input: top 5 features + relevant news summaries + context
- Prompt: "Given this data, predict direction + key risks + confidence (1-10). Reasoning required."
- Output: structured JSON with direction, confidence, reasoning
- Cost control: run only for top-ranked stocks from Model A (e.g., top 15)
- Why LLM: catches nuance models miss (e.g., news says "beat" but guidance cut = actually bearish)

**Ensemble Voter**
- Weighted combination of A + B + C
- Weights learned from historical validation data (higher weight to more-accurate model per regime)
- Final output per stock: `(direction, predicted_high, predicted_low, confidence)`

**Confidence Calibration**
- Raw model probabilities are often miscalibrated
- Apply Platt scaling / isotonic regression using historical validation data
- Goal: "70% confidence" should mean correct ~70% of the time

**Output of Stage 4**: `predictions_today.parquet` — 50 rows with predictions + confidence.

---

### Stage 5 — Report Generation

**Responsibility**: Turn 50 raw predictions into a usable report.

#### Ranking logic
- **BUY candidates**: direction=UP, confidence >= 65%, expected move >= 1%
- **SELL candidates**: direction=DOWN, confidence >= 65%, expected move >= 1%
- Sort by `confidence × expected_move` (conviction × size)
- Take top 5 from each side

#### Report includes
- Overall market bias (bullish/bearish/neutral based on Gift Nifty + global + aggregate sentiment)
- Top 5 BUY table (ticker, predicted range, confidence, key news driver)
- Top 5 SELL table (same)
- Stocks to watch (high uncertainty, big catalyst, earnings today)
- Historical accuracy (last 30 days rolling: direction accuracy %, top-5 hit rate)
- System health (data freshness, model last trained, any warnings)

---

### Stage 6 — Output

**Formats**:

1. **Terminal output** — `rich` library for colored tables, Markdown rendering
   - Fast visual scan
   - Default output when running `python main.py`

2. **Markdown report** — `reports/YYYY-MM-DD.md`
   - Persistent record for later review
   - Human-readable, shareable

3. **JSON dump** — `predictions/YYYY-MM-DD.json`
   - Machine-readable for validation stage
   - Full feature + prediction data

4. **Optional Telegram push** — one-message summary to phone
   - Only if user opts in (requires free bot token)

---

### Stage 7 — Post-Market Validation

**Responsibility**: Measure honestly whether predictions worked.

**Runs at 4:00 PM IST daily** (or manually: `python validate.py`).

**Logic**:
1. Load `predictions/YYYY-MM-DD.json`
2. Fetch today's actual OHLCV for Nifty 50 (yfinance)
3. For each predicted stock:
   - Was direction correct? (actual close vs open)
   - Was actual high/low within predicted range? (range accuracy)
4. For top-5 BUY and top-5 SELL:
   - How many were correct?
   - What was avg return if "traded" at open, exited at close?
5. Append to `validations` SQLite table
6. Update rolling metrics

**Critical honesty rule**: validation NEVER modifies predictions. Append-only ledger.

---

## 4. Data Model (SQLite + Parquet)

SQLite for structured data, Parquet for time series.

### SQLite schema
```sql
CREATE TABLE predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date DATE NOT NULL,
  ticker TEXT NOT NULL,
  direction TEXT,                 -- 'UP' | 'DOWN' | 'FLAT'
  predicted_high REAL,
  predicted_low REAL,
  confidence REAL,                -- 0 to 1
  model_version TEXT,             -- git commit hash
  top_5_rank INTEGER,             -- NULL if not in top 5
  rank_side TEXT,                 -- 'BUY' | 'SELL' | NULL
  reasoning TEXT,                 -- LLM reasoning if applicable
  feature_snapshot TEXT,          -- JSON of feature values used
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (run_date, ticker)
);

CREATE TABLE validations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  prediction_id INTEGER REFERENCES predictions(id),
  run_date DATE NOT NULL,
  ticker TEXT NOT NULL,
  actual_open REAL,
  actual_close REAL,
  actual_high REAL,
  actual_low REAL,
  direction_correct BOOLEAN,
  range_hit BOOLEAN,              -- was actual high/low in predicted range?
  return_pct REAL,
  validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (run_date, ticker)
);

CREATE TABLE news_articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT,
  url TEXT UNIQUE,
  title TEXT,
  published_at TIMESTAMP,
  content TEXT,
  sentiment_score REAL,
  event_type TEXT,
  tickers_mentioned TEXT,         -- JSON array
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_type TEXT,                  -- 'prediction' | 'validation' | 'retrain'
  run_date DATE NOT NULL,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  status TEXT,                    -- 'success' | 'partial' | 'failed'
  error_log TEXT,
  stats_json TEXT                 -- duration, news count, api calls, etc.
);

CREATE TABLE model_metadata (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_name TEXT,                -- 'direction_v1', 'range_v1'
  version TEXT,
  trained_at TIMESTAMP,
  training_data_range TEXT,       -- e.g., "2020-01-01 to 2025-12-31"
  validation_accuracy REAL,
  feature_importance TEXT,        -- JSON
  params TEXT,                    -- JSON
  file_path TEXT                  -- path to pickle
);
```

### Parquet layout (time-series cache)
```
data/
├── market/
│   ├── ohlcv_nifty50.parquet         # all stocks, all history
│   └── global_indices.parquet        # S&P, Nikkei, etc.
├── news/
│   └── YYYY/MM/DD.parquet            # daily snapshots, partitioned
├── features/
│   └── YYYY/MM/DD.parquet            # engineered features per day
└── models/
    ├── direction_v1_20260422.pkl
    └── range_v1_20260422.pkl
```

---

## 5. Repository Structure

```
algo-trading-system/           (folder name kept for continuity)
├── README.md                  (updated for new scope)
├── ARCHITECTURE.md            (this file)
├── REQUIREMENTS.md            (requirements + API details)
├── 01-learning-path.md        (still relevant, reading stays useful)
├── 02-strategy-options.md     (PARTIALLY obsolete — no execution now)
├── 03-tech-stack.md           (needs update)
├── 04-risk-rules.md           (N/A — no trading; keep for reference)
├── 05-30-day-plan.md          (needs rewrite)
├── 06-capital-plan.md         (N/A — no capital deployed)
├── decisions.md               (log the pivot here)
├── todo.md                    (update for new scope)
│
├── pyproject.toml
├── .env.example
├── main.py                    (pre-market run entry)
├── validate.py                (post-market validation entry)
│
├── src/
│   ├── ingestion/
│   │   ├── news/
│   │   │   ├── nse_bse.py
│   │   │   ├── moneycontrol.py
│   │   │   ├── economic_times.py
│   │   │   ├── livemint.py
│   │   │   ├── yahoo_finance.py
│   │   │   └── marketaux.py          # paid, optional
│   │   ├── market/
│   │   │   ├── yfinance_client.py
│   │   │   ├── nsepy_client.py
│   │   │   └── global_indices.py
│   │   └── events/
│   │       └── earnings_calendar.py
│   │
│   ├── nlp/
│   │   ├── dedup.py
│   │   ├── entity_extraction.py
│   │   ├── sentiment/
│   │   │   ├── finbert.py
│   │   │   └── llm_scorer.py         # Claude-based
│   │   ├── event_classifier.py
│   │   └── impact_estimator.py
│   │
│   ├── features/
│   │   ├── news_features.py
│   │   ├── technical.py
│   │   ├── momentum.py
│   │   ├── volatility.py
│   │   ├── market_context.py
│   │   ├── calendar_features.py
│   │   ├── similarity.py
│   │   └── assembler.py
│   │
│   ├── models/
│   │   ├── direction_classifier.py
│   │   ├── range_regressor.py
│   │   ├── llm_reasoner.py
│   │   ├── ensemble.py
│   │   ├── calibration.py
│   │   └── trainer.py
│   │
│   ├── report/
│   │   ├── terminal.py               # Rich tables
│   │   ├── markdown_writer.py
│   │   └── json_writer.py
│   │
│   ├── validation/
│   │   ├── fetch_actuals.py
│   │   ├── metrics.py
│   │   └── rolling_tracker.py
│   │
│   ├── db/
│   │   ├── sqlite_client.py
│   │   └── migrations.py
│   │
│   └── common/
│       ├── config.py
│       ├── logger.py
│       ├── cache.py
│       ├── retry.py
│       └── market_calendar.py
│
├── notebooks/                 # experimentation (CTO plays with numbers here)
│   ├── 01-data-exploration.ipynb
│   ├── 02-feature-analysis.ipynb
│   ├── 03-model-experiments.ipynb
│   └── research/
│
├── configs/
│   ├── nifty50.yaml                  # stock universe
│   ├── news_sources.yaml             # enabled sources + API keys env vars
│   └── model_params.yaml             # hyperparameters (easy to tweak)
│
├── data/                       (gitignored — local cache)
│   ├── market/
│   ├── news/
│   ├── features/
│   └── models/
│
├── reports/                    (gitignored — daily outputs)
│   └── YYYY-MM-DD.md
│
├── predictions/                (gitignored — daily JSON)
│   └── YYYY-MM-DD.json
│
├── logs/                       (gitignored — rotating logs)
│
├── tests/
│   ├── unit/
│   └── fixtures/
│
└── scripts/
    ├── train_models.py               # run weekly
    ├── backtest.py                   # historical validation
    └── explore_accuracy.py           # ad-hoc metric digs
```

---

## 6. Pre-Market Run Flow (step by step)

User types `python main.py` at 8:00 AM IST.

```
[08:00:00] START — run_id = abc123
[08:00:02] Stage 1: Ingestion
           ├─ Fetching news (12 sources, parallel)..........  ok (48 articles)
           ├─ Fetching market data.............................  ok (50 stocks)
           ├─ Fetching global indices..........................  ok (6 indices)
           └─ Fetching events calendar.........................  ok (3 earnings today)
[08:00:18] Stage 2: NLP Processing
           ├─ Deduplication (48 → 36 unique).................. ok
           ├─ Entity extraction (36 articles → 28 mapped).... ok
           ├─ FinBERT sentiment scoring....................... ok
           ├─ LLM deep analysis (top 15 articles)............. ok (₹4.20 cost)
           └─ Event classification............................ ok
[08:00:54] Stage 3: Feature Engineering
           └─ Assembled 50 × 42 feature matrix................ ok
[08:00:57] Stage 4: Prediction
           ├─ Direction classifier (XGBoost)..................  ok
           ├─ Range regressor (XGBoost).......................  ok
           ├─ LLM reasoning (top 15 stocks)...................  ok (₹6.80 cost)
           └─ Ensemble + calibration..........................  ok
[08:01:12] Stage 5: Report generation........................ ok
[08:01:13] Stage 6: Output
           ├─ Terminal (rendered below)
           ├─ Markdown saved: reports/2026-04-22.md
           └─ JSON saved: predictions/2026-04-22.json
[08:01:15] DONE — 1m 15s, total cost ₹11.00

────── Market Bias ──────
  Bullish (GIFT Nifty +0.4%, Global positive, Sentiment +0.3)

────── Top 5 BUY ───────────────────────────────────────────
┌─────┬──────────────┬──────────┬──────────┬────────────┬───────────────────┐
│ #   │ Stock        │ Pred Low │ Pred High│ Confidence │ Key Driver        │
├─────┼──────────────┼──────────┼──────────┼────────────┼───────────────────┤
│  1  │ INFY         │ 1,495    │ 1,530    │ 74%        │ US results beat   │
│  2  │ RELIANCE     │ 2,450    │ 2,495    │ 69%        │ Crude surge       │
│  3  │ HDFCBANK     │ 1,660    │ 1,688    │ 66%        │ Pos macro         │
│  4  │ TCS          │ 4,120    │ 4,180    │ 65%        │ US tech rally     │
│  5  │ BAJFINANCE   │ 6,850    │ 6,980    │ 62%        │ Analyst upgrade   │
└─────┴──────────────┴──────────┴──────────┴────────────┴───────────────────┘

────── Top 5 AVOID/SELL ────────────────────────────────────
(similar table)

────── Rolling Accuracy (last 30 days) ─────
  Direction accuracy: 58.4% (target: 60%)
  Top-5 hit rate: 64% (3.2 of 5 avg)
  Range hit rate: 41%
```

---

## 7. Post-Market Validation Flow

At 4:00 PM IST (or on-demand via `python validate.py`):

```
[16:00:00] VALIDATION — run_id = abc123 (predicted at 08:00)
[16:00:03] Fetching actual OHLCV for 50 stocks............  ok
[16:00:05] Computing accuracy metrics.....................  ok
[16:00:06] Writing to validations table...................  ok

────── Today's Results ──────
  Overall direction accuracy: 31/50 = 62%  ✓ (above 60% target)
  Top 5 BUY correct: 4/5  ✓
  Top 5 SELL correct: 3/5
  Range hits: 22/50 = 44%

────── Rolling 30-day ───────
  Direction: 59.1% → 59.3%
  Top-5 BUY hit rate: 3.1 → 3.2 of 5
  Top-5 SELL hit rate: 2.8 → 2.8 of 5

────── Notable ──────
  Best call:  INFY predicted +2.1%, actual +2.4% (within range ✓)
  Worst call: ICICIBANK predicted -1.2%, actual +1.8% (upside surprise)
  Reason for miss: unreleased RBI guidance leaked mid-day — not in pre-market news
```

---

## 8. Experimentation Framework

User is CTO, will iterate. This is explicitly designed for that.

### How to experiment
```
notebooks/research/
├── exp_001_add_options_oi_feature.ipynb
├── exp_002_try_lightgbm_vs_xgboost.ipynb
├── exp_003_longer_news_window.ipynb
└── ...
```

### Experiment protocol
1. Copy baseline model + features to experiment notebook
2. Make one change at a time (new feature, new model, new data source)
3. Run backtest on held-out period (e.g., last 3 months)
4. Compare metrics to baseline (direction accuracy, top-5 hit rate, Sharpe of "simulated P&L")
5. If better → promote to main codebase, bump `model_version`
6. If worse → document why, archive experiment

### Why this matters
Without discipline, you'll convince yourself every tweak helped. With this framework, you have proof.

---

## 9. Backtesting Strategy

Before going "live" with predictions, we must prove edge on historical data.

### Backtest design
1. **Train period**: 2020-01-01 to 2024-12-31 (5 years including COVID regime)
2. **Validation period**: 2025-01-01 to 2025-12-31 (1 year, held out)
3. **Walk-forward**: retrain every 3 months, test next 3 months
4. **Metrics**:
   - Direction accuracy
   - Top-5 daily hit rate
   - Simulated P&L (assume trade all top-5 at open, close at close — equal weight)
   - Sharpe of simulated P&L
   - Max drawdown of simulated P&L

### Caveats to avoid
- **Look-ahead bias**: news used must be published before 8 AM on that day
- **Survivorship bias**: use Nifty 50 composition as of each historical date (constituents changed)
- **Corporate actions**: adjust historical prices for splits/bonuses
- **Overfit**: too many hyperparameter tweaks on same validation period = overfit to it

### Decision gate
Only after backtest shows:
- Direction accuracy ≥ 58% (with walk-forward, out-of-sample)
- Top-5 hit rate ≥ 3/5 average
- Simulated Sharpe ≥ 1.0 after realistic trading costs

... can we say the system "has edge". Otherwise iterate.

---

## 10. Phased Implementation Roadmap

### Phase 0: Setup (Week 1)
- Project scaffolding
- All Python libs installed
- LLM API key working (test prompt succeeds)
- First `main.py` prints "Hello, system"

### Phase 1: Data Layer (Week 2–3)
- All ingestion modules working
- Historical data (5 years) cached locally
- One day's news + market data flows through stage 1

### Phase 2: Features + Simple Model (Week 4–5)
- Feature engineering complete
- Simple XGBoost direction classifier trained
- First predictions generated (even if bad)
- Terminal output works

### Phase 3: NLP + LLM Integration (Week 6–7)
- FinBERT sentiment working
- Claude integration for top-N stories
- Sentiment features fed into model
- Direction classifier retrained with news features

### Phase 4: Range Model + Ensemble (Week 8)
- Range regressor trained
- Ensemble voter working
- Full report generation

### Phase 5: Validation + Backtesting (Week 9–10)
- Post-market validation flow
- Historical backtest on 2025 held-out data
- Metrics dashboard

### Phase 6: Iteration (Week 11+)
- Daily runs
- Track accuracy
- Experiment weekly
- Improve until >60% target hit (or decide to abandon)

**Decision gate at end of Week 10**: if backtest shows edge, continue. If not, post-mortem + pivot.

---

## 11. Cost Model (Per Run)

### Per daily pre-market run
| Item | Cost |
|------|------|
| News APIs (mostly free tier) | ₹0 |
| yfinance / nsepy | ₹0 (free) |
| FinBERT local inference | ₹0 (CPU/GPU time) |
| Claude LLM (top 15 articles + top 15 predictions) | ₹10–15 |
| Compute (your Mac) | ₹0 |
| **Total per run** | **₹10–15** |

### Monthly (20 trading days)
- **LLM**: ₹200–300 (offset by user's coupons initially)
- **News API (if paid)**: ₹0 (free tier) → ₹2,500 (MarketAux/NewsData)
- **Storage / infra**: ₹0 (local)
- **Total**: **₹200–3,000/month** depending on news tier

---

## 12. Risks & Limitations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Models overfit to training period | High | Walk-forward validation; separate test set |
| News ≠ causality | High | Treat sentiment as ONE feature, not the feature |
| Rare regime (COVID-like) unseen | Medium | Train includes 2020–2024 regimes; warn when features outside training distribution |
| Data source failure at 8 AM | Medium | Fallback sources; graceful degradation; alert |
| LLM output hallucinated | Medium | Structured JSON output only; cross-check with numeric model |
| Self-deception (only looking at good days) | **Critical** | Immutable validation log; weekly honest review |
| Scope creep (adding unvetted features) | Medium | Experiment framework; only promote what beats baseline |
| Predictions cause trading losses | N/A | No trading — purely advisory |

---

## 13. What Success Looks Like (6 months in)

- ✅ System runs daily at 8 AM unattended (user clicks run)
- ✅ Direction accuracy tracks ≥ 58% on rolling 30-day basis
- ✅ Top-5 hit rate averages 3+/5 positive returns
- ✅ User has 20+ documented experiments
- ✅ Next-best-feature research backlog
- ✅ Zero system crashes in last month
- ✅ Validation data shows model didn't overfit

If these are hit → system has edge, worth continuing investment.
If not → honest retro, decide: iterate more vs pivot to project 2 full-time.
