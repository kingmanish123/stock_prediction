-- ─────────────────────────────────────────────────────────────────────
--  Stock Prediction System — Initial Schema (v1.0)
--  Created: 2026-04-22
--  Database: stock_prediction
--  Engine: InnoDB | Charset: utf8mb4
-- ─────────────────────────────────────────────────────────────────────

SET NAMES utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 1: stocks — master catalog of all stocks ever tracked
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stocks (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    symbol                VARCHAR(20) NOT NULL UNIQUE,
    name                  VARCHAR(255) NOT NULL,
    nse_symbol            VARCHAR(20) NOT NULL UNIQUE,
    bse_code              VARCHAR(20) UNIQUE,
    isin                  VARCHAR(20) UNIQUE,
    yfinance_ticker       VARCHAR(30) NOT NULL UNIQUE,
    sector                VARCHAR(100),
    industry              VARCHAR(100),
    market_cap_cr         DECIMAL(15,2),
    currently_active      BOOLEAN DEFAULT TRUE,
    first_seen_date       DATE,
    delisted_date         DATE,
    notes                 TEXT,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_currently_active (currently_active),
    INDEX idx_sector (sector)
) ENGINE=InnoDB CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 2: stock_universe_history — time-versioned Nifty 50 membership
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stock_universe_history (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    universe_name     VARCHAR(30) NOT NULL,
    stock_id          INT NOT NULL,
    valid_from        DATE NOT NULL,
    valid_to          DATE,
    rebalance_event   VARCHAR(50),
    change_reason     VARCHAR(255),
    announcement_url  VARCHAR(512),
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (stock_id) REFERENCES stocks(id),
    INDEX idx_universe_active (universe_name, valid_to),
    INDEX idx_universe_date (universe_name, valid_from, valid_to),
    INDEX idx_stock (stock_id),
    UNIQUE KEY uk_no_overlap (universe_name, stock_id, valid_from)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 3: market_data_daily — Indian stocks OHLCV
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_data_daily (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_id        INT NOT NULL,
    trade_date      DATE NOT NULL,
    open            DECIMAL(12,4),
    high            DECIMAL(12,4),
    low             DECIMAL(12,4),
    close           DECIMAL(12,4),
    adjusted_close  DECIMAL(12,4),
    volume          BIGINT,
    turnover_cr     DECIMAL(15,2),
    num_trades      INT,
    vwap            DECIMAL(12,4),
    delivery_qty    BIGINT,
    delivery_pct    DECIMAL(6,2),
    data_source     VARCHAR(20) DEFAULT 'yfinance',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (stock_id) REFERENCES stocks(id) ON DELETE CASCADE,
    UNIQUE KEY uk_stock_date (stock_id, trade_date),
    INDEX idx_trade_date (trade_date),
    INDEX idx_stock_date_desc (stock_id, trade_date DESC)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 4: global_indices_daily — global market context
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS global_indices_daily (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    index_symbol      VARCHAR(30) NOT NULL,
    index_name        VARCHAR(100) NOT NULL,
    country           VARCHAR(50),
    currency          VARCHAR(10),
    trade_date        DATE NOT NULL,
    open              DECIMAL(15,4),
    high              DECIMAL(15,4),
    low               DECIMAL(15,4),
    close             DECIMAL(15,4),
    volume            BIGINT,
    daily_return_pct  DECIMAL(8,4),
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_index_date (index_symbol, trade_date),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 5: macro_data_daily — macro indicators (FRED + other)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS macro_data_daily (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    indicator_code    VARCHAR(50) NOT NULL,
    indicator_name    VARCHAR(200) NOT NULL,
    category          VARCHAR(50),
    observation_date  DATE NOT NULL,
    value             DECIMAL(20,6),
    unit              VARCHAR(50),
    source            VARCHAR(50) NOT NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_indicator_date (indicator_code, observation_date),
    INDEX idx_observation_date (observation_date),
    INDEX idx_category (category)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 6: news_articles — raw news from all sources
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_articles (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    source              VARCHAR(50) NOT NULL,
    source_article_id   VARCHAR(255),
    url                 VARCHAR(1024),
    title               TEXT NOT NULL,
    summary             TEXT,
    content             LONGTEXT,
    author              VARCHAR(255),
    category            VARCHAR(100),
    published_at        TIMESTAMP NOT NULL,
    fetched_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    language            VARCHAR(10) DEFAULT 'en',
    content_hash        CHAR(64),
    sentiment_score     DECIMAL(5,3),
    sentiment_label     ENUM('negative','neutral','positive'),
    event_type          VARCHAR(50),
    impact_magnitude    DECIMAL(5,3),
    is_processed        BOOLEAN DEFAULT FALSE,
    processed_at        TIMESTAMP NULL,
    llm_analysis        JSON,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_source_article (source, source_article_id),
    UNIQUE KEY uk_content_hash (content_hash),
    INDEX idx_published (published_at),
    INDEX idx_source (source),
    INDEX idx_is_processed (is_processed),
    INDEX idx_event_type (event_type),
    FULLTEXT INDEX ft_title_content (title, content)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 7: article_tickers — news ↔ stocks M2M
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS article_tickers (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    article_id          BIGINT NOT NULL,
    stock_id            INT NOT NULL,
    mention_confidence  DECIMAL(4,3) DEFAULT 1.000,
    extraction_method   ENUM('rule_based','ner','llm','manual') DEFAULT 'rule_based',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (article_id) REFERENCES news_articles(id) ON DELETE CASCADE,
    FOREIGN KEY (stock_id)   REFERENCES stocks(id),
    UNIQUE KEY uk_article_stock (article_id, stock_id),
    INDEX idx_stock (stock_id),
    INDEX idx_article (article_id)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 8: corporate_events — earnings, dividends, etc.
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS corporate_events (
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
    event_time      TIME,
    status          ENUM('upcoming','completed','cancelled') DEFAULT 'upcoming',
    title           VARCHAR(500),
    description     TEXT,
    source          VARCHAR(50),
    source_id       VARCHAR(255),
    metadata        JSON,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (stock_id) REFERENCES stocks(id),
    INDEX idx_stock_date (stock_id, event_date),
    INDEX idx_event_date (event_date),
    INDEX idx_status (status),
    INDEX idx_event_type (event_type)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 9: runs — pipeline execution log
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runs (
    id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_type              ENUM('prediction','validation','backfill','training','experiment') NOT NULL,
    run_date              DATE NOT NULL,
    started_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at          TIMESTAMP NULL,
    status                ENUM('running','success','partial','failed') DEFAULT 'running',
    duration_sec          INT,
    articles_fetched      INT DEFAULT 0,
    articles_processed    INT DEFAULT 0,
    stocks_processed      INT DEFAULT 0,
    predictions_count     INT DEFAULT 0,
    llm_calls_gemini      INT DEFAULT 0,
    llm_calls_claude      INT DEFAULT 0,
    total_cost_inr        DECIMAL(10,2) DEFAULT 0.00,
    error_log             TEXT,
    metadata              JSON,

    INDEX idx_run_type_date (run_type, run_date DESC),
    INDEX idx_status (status),
    INDEX idx_started_at (started_at DESC)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 10: predictions — daily stock predictions (core output)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS predictions (
    id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id                BIGINT NOT NULL,
    run_date              DATE NOT NULL,
    stock_id              INT NOT NULL,
    direction             ENUM('UP','DOWN','FLAT') NOT NULL,
    predicted_low         DECIMAL(12,4),
    predicted_high        DECIMAL(12,4),
    predicted_close       DECIMAL(12,4),
    predicted_return_pct  DECIMAL(8,4),
    confidence            DECIMAL(5,3),
    buy_rank              TINYINT,
    sell_rank             TINYINT,
    model_version         VARCHAR(100) NOT NULL,
    features_snapshot     JSON,
    model_outputs         JSON,
    reasoning             TEXT,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (run_id)   REFERENCES runs(id),
    FOREIGN KEY (stock_id) REFERENCES stocks(id),
    UNIQUE KEY uk_run_date_stock (run_date, stock_id),
    INDEX idx_run (run_id),
    INDEX idx_date_direction (run_date, direction),
    INDEX idx_date_buy_rank (run_date, buy_rank),
    INDEX idx_date_sell_rank (run_date, sell_rank),
    INDEX idx_confidence (confidence)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 11: validations — actual vs predicted
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS validations (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    prediction_id     BIGINT NOT NULL,
    run_date          DATE NOT NULL,
    stock_id          INT NOT NULL,
    actual_open       DECIMAL(12,4),
    actual_high       DECIMAL(12,4),
    actual_low        DECIMAL(12,4),
    actual_close      DECIMAL(12,4),
    actual_volume     BIGINT,
    actual_return_pct DECIMAL(8,4),
    direction_correct BOOLEAN,
    range_hit         BOOLEAN,
    range_overlap_pct DECIMAL(5,3),
    validated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (prediction_id) REFERENCES predictions(id) ON DELETE CASCADE,
    FOREIGN KEY (stock_id)      REFERENCES stocks(id),
    UNIQUE KEY uk_prediction (prediction_id),
    INDEX idx_run_date (run_date),
    INDEX idx_direction_correct (direction_correct)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 12: model_versions — trained model metadata
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS model_versions (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    model_name            VARCHAR(100) NOT NULL,
    version               VARCHAR(50) NOT NULL,
    algorithm             VARCHAR(50),
    trained_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    training_data_from    DATE,
    training_data_to      DATE,
    num_training_samples  INT,
    features_used         JSON,
    hyperparameters       JSON,
    validation_accuracy   DECIMAL(5,3),
    validation_precision  DECIMAL(5,3),
    validation_recall     DECIMAL(5,3),
    validation_f1         DECIMAL(5,3),
    validation_sharpe     DECIMAL(6,3),
    validation_metrics    JSON,
    is_active             BOOLEAN DEFAULT FALSE,
    deployed_at           TIMESTAMP NULL,
    retired_at            TIMESTAMP NULL,
    file_path             VARCHAR(500),
    feature_importance    JSON,
    notes                 TEXT,

    UNIQUE KEY uk_model_version (model_name, version),
    INDEX idx_is_active (is_active),
    INDEX idx_model_name (model_name)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 13: api_costs — LLM + paid API usage tracker
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_costs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id          BIGINT,
    service         VARCHAR(50) NOT NULL,
    endpoint        VARCHAR(100),
    model           VARCHAR(100),
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

-- ─────────────────────────────────────────────────────────────────────
--  TABLE 14: daily_metrics — rolling performance aggregates
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_metrics (
    id                              INT AUTO_INCREMENT PRIMARY KEY,
    metric_date                     DATE NOT NULL,
    total_predictions               INT,
    direction_correct_count         INT,
    direction_accuracy              DECIMAL(5,3),
    top5_buy_correct                TINYINT,
    top5_sell_correct               TINYINT,
    top5_buy_avg_return_pct         DECIMAL(8,4),
    top5_sell_avg_return_pct        DECIMAL(8,4),
    range_hit_count                 INT,
    range_hit_rate                  DECIMAL(5,3),
    rolling_30d_direction_accuracy  DECIMAL(5,3),
    rolling_30d_top5_buy_hit_rate   DECIMAL(5,3),
    rolling_30d_top5_sell_hit_rate  DECIMAL(5,3),
    rolling_30d_simulated_return    DECIMAL(8,4),
    run_duration_sec                INT,
    articles_count                  INT,
    total_cost_inr                  DECIMAL(10,2),
    computed_at                     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_date (metric_date),
    INDEX idx_date (metric_date DESC)
) ENGINE=InnoDB CHARSET=utf8mb4;

-- ─────────────────────────────────────────────────────────────────────
--  End of schema — 14 tables created
-- ─────────────────────────────────────────────────────────────────────
