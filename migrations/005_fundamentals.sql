-- Stock fundamentals — refreshed weekly/monthly from yfinance .info
-- One row per stock per snapshot_date (UPSERT on conflict).

CREATE TABLE IF NOT EXISTS stock_fundamentals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_id INT NOT NULL,
    snapshot_date DATE NOT NULL,

    -- Valuation
    pe_ratio DECIMAL(10, 3),              -- trailing P/E
    forward_pe DECIMAL(10, 3),
    pb_ratio DECIMAL(10, 3),              -- price-to-book
    ps_ratio DECIMAL(10, 3),              -- price-to-sales
    peg_ratio DECIMAL(10, 3),             -- P/E to growth
    ev_to_ebitda DECIMAL(10, 3),

    -- Market cap + shares
    market_cap_cr DECIMAL(18, 2),         -- crores
    shares_outstanding BIGINT,
    float_shares BIGINT,

    -- Profitability / returns
    profit_margin DECIMAL(8, 4),          -- net margin (fraction)
    operating_margin DECIMAL(8, 4),
    roe DECIMAL(8, 4),                    -- return on equity
    roa DECIMAL(8, 4),                    -- return on assets

    -- Growth
    revenue_growth_yoy DECIMAL(8, 4),     -- YoY (fraction)
    earnings_growth_yoy DECIMAL(8, 4),
    quarterly_earnings_growth DECIMAL(8, 4),

    -- Financial health
    debt_to_equity DECIMAL(8, 3),
    current_ratio DECIMAL(8, 3),
    total_cash_cr DECIMAL(15, 2),
    total_debt_cr DECIMAL(15, 2),

    -- Dividend
    dividend_yield DECIMAL(8, 4),
    payout_ratio DECIMAL(8, 4),

    -- Price context (at snapshot)
    current_price DECIMAL(12, 4),
    fifty_two_week_high DECIMAL(12, 4),
    fifty_two_week_low DECIMAL(12, 4),
    beta DECIMAL(6, 3),

    -- Metadata
    data_source VARCHAR(30) DEFAULT 'yfinance',
    raw_json JSON,                         -- full snapshot for debugging
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (stock_id) REFERENCES stocks(id) ON DELETE CASCADE,
    UNIQUE KEY uk_stock_snapshot (stock_id, snapshot_date),
    KEY idx_snapshot_date (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
