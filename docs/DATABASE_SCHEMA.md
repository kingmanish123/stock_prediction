# Database Schema Design — MySQL (MariaDB via XAMPP)

**Version**: 1.0
**Last updated**: 2026-04-22
**Engine**: InnoDB
**Charset**: utf8mb4 / utf8mb4_unicode_ci
**Database name**: `stock_prediction`

---

## Design philosophy

1. **MySQL for structured data, Parquet for bulk time-series features** — queryability + performance balance
2. **Every table has a clear single purpose** — no god tables
3. **Foreign keys enforced** — data integrity over raw speed
4. **Immutable audit logs** — predictions + validations append-only, never update/delete
5. **JSON columns for flexibility** — feature snapshots, model outputs, metadata (queryable via `JSON_EXTRACT`)
6. **Explicit indexing** — every common query has a matching index
7. **Rich enums** — constrained vocabulary for status fields

---

## High-level ERD (relationships)

```
                          ┌─────────┐       ┌──────────────────────┐
                          │ stocks  │◄──────│ stock_universe_      │
                          │(master) │       │   history            │
                          └────┬────┘       │ (time-versioned      │
                               │            │  Nifty 50 members)   │
                               │            └──────────────────────┘
           ┌───────────────────┼───────────────────┬───────────────┐
           │                   │                   │               │
           ▼                   ▼                   ▼               ▼
  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌───────────────┐
  │ market_data    │  │ corporate_     │  │ article_       │  │ predictions   │
  │   _daily       │  │   events       │  │   tickers      │  │               │
  │ (OHLCV x time) │  │ (earnings etc) │  │ (M2M news-stk) │  │ (daily calls) │
  └────────────────┘  └────────────────┘  └───────┬────────┘  └───────┬───────┘
                                                   │                    │
                                                   ▼                    ▼
                                          ┌────────────────┐   ┌───────────────┐
                                          │ news_articles  │   │ validations   │
                                          │ (raw news)     │   │ (actuals)     │
                                          └────────────────┘   └───────────────┘
                                                   │
                                                   │
  ┌────────────────┐  ┌────────────────┐   ┌──────┴──────┐   ┌────────────────┐
  │ global_        │  │ macro_data_    │   │    runs     │   │ model_versions │
  │ indices_daily  │  │    daily       │   │ (exec logs) │   │ (ML tracking)  │
  │ (S&P, Nikkei)  │  │ (VIX, DXY etc) │   └──────┬──────┘   └────────────────┘
  └────────────────┘  └────────────────┘          │
                                                   ▼
                                          ┌────────────────┐   ┌────────────────┐
                                          │  api_costs     │   │ daily_metrics  │
                                          │ (LLM + news)   │   │ (rolling perf) │
                                          └────────────────┘   └────────────────┘
```

---

## Tables at a glance

| # | Table | Purpose | Est. rows/year |
|---|-------|---------|----------------|
| 1 | `stocks` | Master list of all ever-known stocks | ~50-100 (grows slowly) |
| 2 | `stock_universe_history` | **Time-versioned Nifty 50 composition** | 5-10 entries/year |
| 3 | `market_data_daily` | Indian stocks OHLCV | ~12,500 |
| 4 | `global_indices_daily` | S&P, Nasdaq, Nikkei, etc. | ~2,000 |
| 5 | `macro_data_daily` | VIX, DXY, crude, Fed rate | ~2,500 |
| 6 | `news_articles` | All news sources raw | ~15,000 |
| 7 | `article_tickers` | News ↔ stocks M2M | ~30,000 |
| 8 | `corporate_events` | Earnings, results, dividends | ~500 |
| 9 | `runs` | Pre-market + post-market runs | ~500 |
| 10 | `predictions` | Daily stock predictions | ~12,500 |
| 11 | `validations` | Actual vs predicted | ~12,500 |
| 12 | `model_versions` | Trained model metadata | ~50 |
| 13 | `api_costs` | LLM + paid API usage tracking | ~5,000 |
| 14 | `daily_metrics` | Rolling accuracy aggregates | ~250 |

**Total annual data**: ~95K rows — MariaDB handles this trivially. Even 5 years = 475K rows, still sub-second queries.

---

## 1. `stocks` — Stock Master (all stocks ever seen)

Catalog of every stock we've ever tracked — current Nifty 50 + historically removed ones. Pure reference table; membership/activity is in `stock_universe_history`.

```sql
CREATE TABLE stocks (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    symbol                VARCHAR(20) NOT NULL UNIQUE,      -- canonical symbol, e.g., 'RELIANCE'
    name                  VARCHAR(255) NOT NULL,            -- full company name
    nse_symbol            VARCHAR(20) NOT NULL UNIQUE,      -- NSE ticker
    bse_code              VARCHAR(20) UNIQUE,               -- BSE numeric code, e.g., '500325'
    isin                  VARCHAR(20) UNIQUE,               -- global ID
    yfinance_ticker       VARCHAR(30) NOT NULL UNIQUE,      -- e.g., 'RELIANCE.NS'
    sector                VARCHAR(100),
    industry              VARCHAR(100),
    market_cap_cr         DECIMAL(15,2),                    -- latest snapshot
    currently_active      BOOLEAN DEFAULT TRUE,             -- convenience flag; authoritative = stock_universe_history
    first_seen_date       DATE,                             -- when first added to our tracking
    delisted_date         DATE,                             -- if fully delisted
    notes                 TEXT,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_currently_active (currently_active),
    INDEX idx_sector (sector)
) ENGINE=InnoDB CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**Seed**: populated with current Nifty 50 + any historically-removed Nifty 50 stocks we want backtest coverage for.

---

## 2. `stock_universe_history` — Time-Versioned Index Membership

**This is the critical table for survivorship-bias-free backtests.**

Tracks which stocks were in the Nifty 50 (or any other index) on any given date. A stock can have multiple rows — in, out, back in.

```sql
CREATE TABLE stock_universe_history (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    universe_name     VARCHAR(30) NOT NULL,              -- 'NIFTY50', 'NIFTY100', 'NIFTY500'
    stock_id          INT NOT NULL,
    valid_from        DATE NOT NULL,                     -- inclusive: first day this stock was in
    valid_to          DATE,                              -- exclusive end; NULL = currently active
    rebalance_event   VARCHAR(50),                       -- 'MARCH_2023', 'SEPTEMBER_2023', 'INITIAL'
    change_reason     VARCHAR(255),                      -- 'added - top market cap', 'removed - merged'
    announcement_url  VARCHAR(512),                      -- link to NSE press release
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (stock_id) REFERENCES stocks(id),
    INDEX idx_universe_active (universe_name, valid_to),
    INDEX idx_universe_date (universe_name, valid_from, valid_to),
    INDEX idx_stock (stock_id),
    UNIQUE KEY uk_no_overlap (universe_name, stock_id, valid_from)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

### How this table solves the problem

**Question**: "Which stocks were in Nifty 50 on 2023-06-15?"
```sql
SELECT s.symbol, s.name
FROM stock_universe_history uh
JOIN stocks s ON s.id = uh.stock_id
WHERE uh.universe_name = 'NIFTY50'
  AND uh.valid_from <= '2023-06-15'
  AND (uh.valid_to IS NULL OR uh.valid_to > '2023-06-15');
```

**Question**: "Current Nifty 50?"
```sql
SELECT s.symbol, s.name
FROM stock_universe_history uh
JOIN stocks s ON s.id = uh.stock_id
WHERE uh.universe_name = 'NIFTY50'
  AND uh.valid_to IS NULL;
```

### Seed strategy (pragmatic)

- **V1 (now)**: Seed with current Nifty 50 as of 2026-04-22 — one row per stock, `valid_from=2026-04-22`, `valid_to=NULL`, `rebalance_event='INITIAL'`
- **When backtesting Phase 5**: backfill historical rebalance events by scraping NSE press releases (list below)

### Known historical rebalance events (for future backfill)

Source: https://www.nseindia.com/products-services/equity-market-indices (Index Maintenance Archives)

| Date | Event | Stocks Added | Stocks Removed |
|------|-------|--------------|----------------|
| Mar 2020 | Semi-annual | Shree Cement, Nestle India | Indiabulls Housing, Zee |
| Sep 2020 | Semi-annual | Divi's Labs, SBI Life | Bharti Infratel, Vedanta |
| Mar 2021 | Semi-annual | Tata Consumer | GAIL |
| Mar 2022 | Semi-annual | Apollo Hospitals | IOC |
| Sep 2022 | Semi-annual | Adani Enterprises, Adani Ports | Shree Cement |
| Mar 2023 | Semi-annual | LTIMindtree | ... |
| Sep 2023 | Semi-annual | JIO Financial Services, LTIMindtree | ... |
| ...  | ... | ... | ... |

(Incomplete — populate during backfill phase.)

### Maintenance

- Cron job every March + September 1st checks NSE announcements for new composition
- Alert via Telegram (when enabled) when change detected
- Apply via migration: insert new rows with `valid_from = rebalance_effective_date`, update old row's `valid_to`

---

## 3. `market_data_daily` — Indian Stocks OHLCV

Daily OHLCV for all Nifty 50 stocks.

```sql
CREATE TABLE market_data_daily (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_id        INT NOT NULL,
    trade_date      DATE NOT NULL,
    open            DECIMAL(12,4),
    high            DECIMAL(12,4),
    low             DECIMAL(12,4),
    close           DECIMAL(12,4),
    adjusted_close  DECIMAL(12,4),                  -- adjusted for splits/bonuses
    volume          BIGINT,
    turnover_cr     DECIMAL(15,2),                  -- traded value in ₹ crores
    num_trades      INT,
    vwap            DECIMAL(12,4),                  -- volume-weighted average price
    delivery_qty    BIGINT,                         -- delivery qty (NSE reports this)
    delivery_pct    DECIMAL(6,2),                   -- delivery %, indicates conviction
    data_source     VARCHAR(20) DEFAULT 'yfinance', -- provenance
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (stock_id) REFERENCES stocks(id) ON DELETE CASCADE,
    UNIQUE KEY uk_stock_date (stock_id, trade_date),
    INDEX idx_trade_date (trade_date),
    INDEX idx_stock_date (stock_id, trade_date DESC)   -- common: latest N days per stock
) ENGINE=InnoDB CHARSET=utf8mb4;
```

**Population**: bulk backfill 5 years on first run; incremental daily post-market.

---

## 4. `global_indices_daily` — Global Market Context

S&P 500, Nasdaq, Dow, Nikkei, Hang Seng, DAX, FTSE, Gift Nifty.

```sql
CREATE TABLE global_indices_daily (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    index_symbol      VARCHAR(30) NOT NULL,       -- e.g., '^GSPC', '^IXIC', 'GIFTNIFTY'
    index_name        VARCHAR(100) NOT NULL,      -- 'S&P 500', 'Nasdaq Composite'
    country           VARCHAR(50),
    currency          VARCHAR(10),
    trade_date        DATE NOT NULL,
    open              DECIMAL(15,4),
    high              DECIMAL(15,4),
    low               DECIMAL(15,4),
    close             DECIMAL(15,4),
    volume            BIGINT,
    daily_return_pct  DECIMAL(8,4),               -- computed: (close - prev_close) / prev_close * 100
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_index_date (index_symbol, trade_date),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

---

## 5. `macro_data_daily` — Macro Indicators (FRED + other)

VIX, DXY, crude, Fed rate, India 10Y yield, CPI, etc.

```sql
CREATE TABLE macro_data_daily (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    indicator_code    VARCHAR(50) NOT NULL,       -- e.g., 'VIXCLS', 'DTWEXBGS', 'DGS10'
    indicator_name    VARCHAR(200) NOT NULL,      -- human-readable
    category          VARCHAR(50),                -- 'volatility', 'fx', 'rates', 'commodity'
    observation_date  DATE NOT NULL,
    value             DECIMAL(20,6),
    unit              VARCHAR(50),
    source            VARCHAR(50) NOT NULL,       -- 'fred', 'yfinance', 'manual'
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_indicator_date (indicator_code, observation_date),
    INDEX idx_observation_date (observation_date),
    INDEX idx_category (category)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

**Seed macros**:
- `VIXCLS` (CBOE VIX)
- `DTWEXBGS` (US Dollar Index)
- `DGS10` (US 10Y treasury)
- `DCOILWTICO` (WTI crude)
- `FEDFUNDS` (Fed funds rate)

---

## 6. `news_articles` — All News, All Sources

Central table for every scraped article.

```sql
CREATE TABLE news_articles (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    source              VARCHAR(50) NOT NULL,             -- 'nse', 'bse', 'moneycontrol', 'et', 'livemint', 'finnhub', etc.
    source_article_id   VARCHAR(255),                     -- original ID from source
    url                 VARCHAR(1024),
    title               TEXT NOT NULL,
    summary             TEXT,
    content             LONGTEXT,
    author              VARCHAR(255),
    category            VARCHAR(100),
    published_at        TIMESTAMP NOT NULL,
    fetched_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    language            VARCHAR(10) DEFAULT 'en',
    content_hash        CHAR(64),                         -- SHA-256 of title+content for dedup

    -- NLP-derived (populated by Stage 2 of pipeline)
    sentiment_score     DECIMAL(5,3),                     -- -1.000 to +1.000
    sentiment_label     ENUM('negative','neutral','positive'),
    event_type          VARCHAR(50),                      -- 'earnings', 'M&A', 'regulatory', etc.
    impact_magnitude    DECIMAL(5,3),                     -- 0.000 to 1.000
    is_processed        BOOLEAN DEFAULT FALSE,
    processed_at        TIMESTAMP NULL,
    llm_analysis        JSON,                             -- Claude/Gemini analysis output

    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_source_article (source, source_article_id),
    UNIQUE KEY uk_content_hash (content_hash),
    INDEX idx_published (published_at),
    INDEX idx_source (source),
    INDEX idx_is_processed (is_processed),
    INDEX idx_event_type (event_type),
    FULLTEXT INDEX ft_title_content (title, content)     -- for text search
) ENGINE=InnoDB CHARSET=utf8mb4;
```

**Dedup strategy**: SHA-256 of normalized title+content. Same story from 3 sources = 3 rows with different `source` but same `content_hash`. Can collapse during analysis.

---

## 7. `article_tickers` — News ↔ Stocks (Many-to-Many)

An article can mention multiple stocks; a stock has many articles.

```sql
CREATE TABLE article_tickers (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    article_id          BIGINT NOT NULL,
    stock_id            INT NOT NULL,
    mention_confidence  DECIMAL(4,3) DEFAULT 1.000,       -- 0-1; rule-based = 1.0, NER = 0.7-0.95
    extraction_method   ENUM('rule_based','ner','llm','manual') DEFAULT 'rule_based',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (article_id) REFERENCES news_articles(id) ON DELETE CASCADE,
    FOREIGN KEY (stock_id)   REFERENCES stocks(id),
    UNIQUE KEY uk_article_stock (article_id, stock_id),
    INDEX idx_stock (stock_id),
    INDEX idx_article (article_id)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

---

## 8. `corporate_events` — Earnings, Results, Dividends

Scheduled and past corporate actions.

```sql
CREATE TABLE corporate_events (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_id        INT NOT NULL,
    event_type      ENUM(
                      'earnings_announcement',
                      'board_meeting',
                      'dividend',
                      'bonus',
                      'split',
                      'rights_issue',
                      'buyback',
                      'merger',
                      'acquisition',
                      'management_change',
                      'credit_rating',
                      'regulatory',
                      'other'
                    ) NOT NULL,
    event_date      DATE NOT NULL,
    event_time      TIME,                             -- NULL if all-day event
    status          ENUM('upcoming','completed','cancelled') DEFAULT 'upcoming',
    title           VARCHAR(500),
    description     TEXT,
    source          VARCHAR(50),                      -- 'nse', 'finnhub', etc.
    source_id       VARCHAR(255),
    metadata        JSON,                             -- actuals vs estimates for earnings
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (stock_id) REFERENCES stocks(id),
    INDEX idx_stock_date (stock_id, event_date),
    INDEX idx_event_date (event_date),
    INDEX idx_status (status),
    INDEX idx_event_type (event_type)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

---

## 9. `runs` — Execution Log

Every pipeline run (pre-market, validation, training, backfill, experiments).

```sql
CREATE TABLE runs (
    id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_type              ENUM('prediction','validation','backfill','training','experiment') NOT NULL,
    run_date              DATE NOT NULL,
    started_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at          TIMESTAMP NULL,
    status                ENUM('running','success','partial','failed') DEFAULT 'running',
    duration_sec          INT,

    -- Stats
    articles_fetched      INT DEFAULT 0,
    articles_processed    INT DEFAULT 0,
    stocks_processed      INT DEFAULT 0,
    predictions_count     INT DEFAULT 0,

    -- Cost tracking (denormalized aggregate from api_costs)
    llm_calls_gemini      INT DEFAULT 0,
    llm_calls_claude      INT DEFAULT 0,
    total_cost_inr        DECIMAL(10,2) DEFAULT 0,

    -- Errors / notes
    error_log             TEXT,
    metadata              JSON,                       -- stage-wise durations, etc.

    INDEX idx_run_type_date (run_type, run_date DESC),
    INDEX idx_status (status),
    INDEX idx_started_at (started_at DESC)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

---

## 10. `predictions` — Daily Stock Predictions (core output)

One row per stock per day. Immutable after insert.

```sql
CREATE TABLE predictions (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id              BIGINT NOT NULL,
    run_date            DATE NOT NULL,
    stock_id            INT NOT NULL,

    -- Core predictions
    direction           ENUM('UP','DOWN','FLAT') NOT NULL,
    predicted_low       DECIMAL(12,4),
    predicted_high      DECIMAL(12,4),
    predicted_close     DECIMAL(12,4),
    predicted_return_pct DECIMAL(8,4),
    confidence          DECIMAL(5,3),                  -- 0.000 to 1.000 (calibrated)

    -- Ranking (NULL if not in top 5)
    buy_rank            TINYINT,                       -- 1-5, NULL otherwise
    sell_rank           TINYINT,                       -- 1-5, NULL otherwise

    -- Model provenance
    model_version       VARCHAR(100) NOT NULL,         -- e.g., 'direction_v1_20260422'
    features_snapshot   JSON,                          -- all feature values used
    model_outputs       JSON,                          -- raw outputs from each sub-model
    reasoning           TEXT,                          -- LLM reasoning if applicable

    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (run_id)   REFERENCES runs(id),
    FOREIGN KEY (stock_id) REFERENCES stocks(id),
    UNIQUE KEY uk_run_date_stock (run_date, stock_id),  -- one pred per stock per day
    INDEX idx_run (run_id),
    INDEX idx_date_direction (run_date, direction),
    INDEX idx_date_buy_rank (run_date, buy_rank),
    INDEX idx_date_sell_rank (run_date, sell_rank),
    INDEX idx_confidence (confidence)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

---

## 11. `validations` — Actual vs Predicted

Filled in by post-market run at 4 PM.

```sql
CREATE TABLE validations (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    prediction_id     BIGINT NOT NULL,
    run_date          DATE NOT NULL,
    stock_id          INT NOT NULL,

    -- Actuals
    actual_open       DECIMAL(12,4),
    actual_high       DECIMAL(12,4),
    actual_low        DECIMAL(12,4),
    actual_close      DECIMAL(12,4),
    actual_volume     BIGINT,
    actual_return_pct DECIMAL(8,4),

    -- Correctness
    direction_correct BOOLEAN,                         -- predicted direction vs actual
    range_hit         BOOLEAN,                         -- did actual H/L fall in predicted range
    range_overlap_pct DECIMAL(5,3),                    -- how much of actual range was in predicted

    validated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (prediction_id) REFERENCES predictions(id) ON DELETE CASCADE,
    FOREIGN KEY (stock_id)      REFERENCES stocks(id),
    UNIQUE KEY uk_prediction (prediction_id),
    INDEX idx_run_date (run_date),
    INDEX idx_direction_correct (direction_correct)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

---

## 12. `model_versions` — Trained Model Metadata

Each retrain creates a new row. Track which model made which prediction.

```sql
CREATE TABLE model_versions (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    model_name            VARCHAR(100) NOT NULL,       -- 'direction_classifier', 'range_regressor', 'llm_reasoner'
    version               VARCHAR(50) NOT NULL,        -- e.g., 'v1_20260422'
    algorithm             VARCHAR(50),                 -- 'xgboost', 'lightgbm', 'claude_prompt_v2'

    -- Training
    trained_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    training_data_from    DATE,
    training_data_to      DATE,
    num_training_samples  INT,
    features_used         JSON,                        -- list of feature names
    hyperparameters       JSON,

    -- Validation metrics (on held-out set)
    validation_accuracy   DECIMAL(5,3),
    validation_precision  DECIMAL(5,3),
    validation_recall     DECIMAL(5,3),
    validation_f1         DECIMAL(5,3),
    validation_sharpe     DECIMAL(6,3),                -- if simulated PnL
    validation_metrics    JSON,                        -- all metrics catchall

    -- Deployment
    is_active             BOOLEAN DEFAULT FALSE,
    deployed_at           TIMESTAMP NULL,
    retired_at            TIMESTAMP NULL,
    file_path             VARCHAR(500),                -- path to .pkl / .json
    feature_importance    JSON,

    notes                 TEXT,

    UNIQUE KEY uk_model_version (model_name, version),
    INDEX idx_is_active (is_active),
    INDEX idx_model_name (model_name)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

---

## 13. `api_costs` — LLM + Paid API Usage Tracker

Every external API call logged for cost awareness.

```sql
CREATE TABLE api_costs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id          BIGINT,
    service         VARCHAR(50) NOT NULL,              -- 'gemini', 'claude', 'finnhub', 'fred'
    endpoint        VARCHAR(100),
    model           VARCHAR(100),                      -- 'gemini-2.5-flash', 'claude-sonnet-4-6'
    tokens_in       INT,
    tokens_out      INT,
    cost_usd        DECIMAL(10,6),
    cost_inr        DECIMAL(10,4),
    duration_ms     INT,
    success         BOOLEAN DEFAULT TRUE,
    error_message   TEXT,
    called_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE SET NULL,
    INDEX idx_run_service (run_id, service),
    INDEX idx_called_at (called_at),
    INDEX idx_service_date (service, called_at)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

---

## 14. `daily_metrics` — Rolling Performance

Materialized aggregates, computed post-validation daily.

```sql
CREATE TABLE daily_metrics (
    id                              INT AUTO_INCREMENT PRIMARY KEY,
    metric_date                     DATE NOT NULL,

    -- Daily accuracy
    total_predictions               INT,
    direction_correct_count         INT,
    direction_accuracy              DECIMAL(5,3),

    top5_buy_correct                TINYINT,                  -- of 5 BUY picks
    top5_sell_correct               TINYINT,                  -- of 5 SELL picks
    top5_buy_avg_return_pct         DECIMAL(8,4),
    top5_sell_avg_return_pct        DECIMAL(8,4),

    range_hit_count                 INT,
    range_hit_rate                  DECIMAL(5,3),

    -- Rolling (trailing 30 days)
    rolling_30d_direction_accuracy  DECIMAL(5,3),
    rolling_30d_top5_buy_hit_rate   DECIMAL(5,3),
    rolling_30d_top5_sell_hit_rate  DECIMAL(5,3),
    rolling_30d_simulated_return    DECIMAL(8,4),             -- if bought top-5 at open, sold at close

    -- System health
    run_duration_sec                INT,
    articles_count                  INT,
    total_cost_inr                  DECIMAL(10,2),

    computed_at                     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_date (metric_date),
    INDEX idx_date (metric_date DESC)
) ENGINE=InnoDB CHARSET=utf8mb4;
```

---

## Data lifecycle

### Daily write flow
```
08:00  Pre-market run:
         → runs (1 row, status=running)
         → news_articles (50-100 rows)
         → article_tickers (100-200 rows)
         → macro_data_daily (latest values for 5-10 indicators)
         → global_indices_daily (prev close for 6-8 indices)
         → predictions (50 rows, one per Nifty stock)
         → runs (update: status=success, duration)
         → api_costs (10-30 rows)

16:00  Post-market validation:
         → runs (1 row, run_type=validation)
         → market_data_daily (50 rows, today's OHLCV)
         → validations (50 rows)
         → daily_metrics (1 row, today's aggregate)
         → runs (update)
```

### Backfill flows
- **One-time**: 5 years of `market_data_daily` + `global_indices_daily` + `macro_data_daily`
- **Weekly**: `corporate_events` refresh from NSE + Finnhub earnings calendar
- **On-demand**: re-generate features, retrain models, populate `model_versions`

### Never deleted
- `predictions`, `validations` — audit trail
- `runs` — execution history
- `api_costs` — cost history
- `news_articles` — archive (for later re-analysis with better models)

---

## Parquet usage (complementary to MySQL)

Not everything goes in MySQL. Parquet files for:

| Data | Location | Why |
|------|----------|-----|
| Daily feature matrix (50 stocks × 40 features) | `data/features/YYYY/MM/DD.parquet` | Fast columnar I/O for ML training |
| Training datasets (historical features + targets) | `data/training/<model_version>.parquet` | Versioned, reproducible training |
| Trained model artifacts | `models/<name>_<version>.pkl` | Binary files don't belong in MySQL |

---

## Indexing strategy

### Common queries + matching indexes

| Query | Index |
|-------|-------|
| Latest N days OHLCV for stock X | `market_data_daily.idx_stock_date` |
| All predictions for date D | `predictions.uk_run_date_stock` |
| Top 5 BUY for date D | `predictions.idx_date_buy_rank` |
| Unprocessed news articles | `news_articles.idx_is_processed` |
| News mentioning stock X | `article_tickers.idx_stock` |
| Upcoming earnings | `corporate_events.idx_event_date` + `idx_status` |
| Rolling 30-day accuracy | `daily_metrics.idx_date` |
| Full-text search on news | `news_articles.ft_title_content` |

---

## Migrations & versioning

- **Initial schema**: `migrations/001_initial_schema.sql`
- **Seed data**: `migrations/002_seed_nifty50.sql` (populates `stocks` table)
- **Future changes**: each migration gets its own numbered file; never edit old ones
- Use **Alembic** (SQLAlchemy migration tool) for Python-driven migrations later

---

## Backup strategy

- **Daily dump** at 5:00 PM IST (after validation completes):
  `mysqldump -u root stock_prediction > backups/YYYY-MM-DD.sql`
- **Retain**: last 30 daily + 12 monthly dumps
- **Location**: `backups/` folder (gitignored)
- **Test restore** quarterly

---

## What's NOT in this schema (yet)

Future additions (V2+), don't need now:

- `experiments` table (A/B testing of features/models)
- `intraday_ticks` (if moving to intraday predictions)
- `user_annotations` (if manual overrides/notes added later)
- `reddit_sentiment_daily` (if Reddit enabled later)

Add via migrations when needed.

---

## Design decisions & rationale

| Decision | Rationale |
|----------|-----------|
| MySQL over SQLite | User has XAMPP running; phpMyAdmin browse; better scale headroom |
| Separate `stock_universe_history` table | **Critical — prevents survivorship bias in backtests.** Nifty 50 rebalances semi-annually; using current composition for historical backtests gives falsely inflated metrics |
| Separate `article_tickers` M2M table | One article can mention many stocks; one stock has many articles |
| `content_hash` dedup on news | Same story from 3 sources = dedup analytics later without losing provenance |
| JSON columns for `features_snapshot` / `metadata` | Flexible schema without migrations when feature set changes |
| `daily_metrics` materialized | Rolling stats should be cheap; compute once, query many |
| `model_versions` table | Reproducibility: link every prediction to exact model + features |
| `api_costs` table | Cost awareness is critical; track every LLM + paid API call |
| Immutable predictions + validations | Never rewrite history; honest audit trail |
| ENUMs for status fields | Prevents typos, improves index efficiency |
| FOREIGN KEYs everywhere possible | Data integrity over raw insert speed (InnoDB handles this well) |

---

## Total estimated disk usage

| Table | Rows/year | Avg row size | Annual size |
|-------|-----------|--------------|-------------|
| market_data_daily | 12,500 | 100 B | 1.2 MB |
| global_indices_daily | 2,000 | 100 B | 0.2 MB |
| macro_data_daily | 2,500 | 150 B | 0.4 MB |
| news_articles | 15,000 | 5 KB (content) | 75 MB |
| article_tickers | 30,000 | 40 B | 1.2 MB |
| corporate_events | 500 | 500 B | 0.25 MB |
| runs | 500 | 1 KB | 0.5 MB |
| predictions | 12,500 | 2 KB (JSON) | 25 MB |
| validations | 12,500 | 200 B | 2.5 MB |
| api_costs | 5,000 | 200 B | 1 MB |
| daily_metrics | 250 | 250 B | 0.06 MB |
| **Total/year** | | | **~107 MB** |

Over 5 years: ~0.5 GB — trivial for MySQL on a laptop.

---

## Ready to implement?

If you're happy with this design, next step is:

1. Create `migrations/001_initial_schema.sql` with all DDL
2. Run migration against `stock_prediction` database
3. Create `src/db/models.py` with SQLAlchemy ORM models matching schema
4. Create `migrations/002_seed_nifty50.sql` with Nifty 50 stocks
5. Verify via phpMyAdmin
6. Then move to actual data ingestion code
