-- Algo experiments registry — one row per backtest run of a named algo variant.
-- Lets us compare multiple prediction configurations over the same date window
-- and track which variant is winning.

CREATE TABLE IF NOT EXISTS algo_experiments (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    algo_name VARCHAR(100) NOT NULL,          -- e.g. "news_driven_v2_atr_stops"
    algo_version VARCHAR(50) NOT NULL,        -- e.g. "2026-04-24-a"

    -- Window
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    trading_days_covered INT,

    -- Config (JSON — copy of all knobs used for this run)
    config_json JSON,

    -- Aggregate metrics across the full window
    total_trades INT DEFAULT 0,
    direction_correct INT DEFAULT 0,
    direction_accuracy DECIMAL(5, 3),

    target_hits INT DEFAULT 0,
    stop_hits INT DEFAULT 0,
    holds INT DEFAULT 0,
    skipped_gap INT DEFAULT 0,

    total_pnl_pct DECIMAL(10, 4),             -- sum of per-trade pnl
    avg_pnl_pct DECIMAL(10, 4),               -- mean per trade
    win_rate DECIMAL(5, 3),                   -- % of trades with positive pnl
    sharpe_ratio DECIMAL(6, 3),               -- rough intraday Sharpe

    max_drawdown_pct DECIMAL(8, 4),
    best_trade_pct DECIMAL(10, 4),
    worst_trade_pct DECIMAL(10, 4),

    -- Per-date breakdown (JSON array of {date, pnl, accuracy})
    per_day_results JSON,

    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_algo_version_window (algo_name, algo_version, start_date, end_date),
    KEY idx_algo_name (algo_name),
    KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
