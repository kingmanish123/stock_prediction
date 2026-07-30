-- ─────────────────────────────────────────────────────────────────────
--  news_themes — LLM-extracted structured insights per news article
-- ─────────────────────────────────────────────────────────────────────

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS news_themes (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    article_id        BIGINT NOT NULL,
    theme_key         VARCHAR(50),              -- canonical (e.g., 'crude_oil_supply') or 'other'
    theme_label       VARCHAR(300),             -- human-readable one-liner
    direction         ENUM('bullish','bearish','neutral'),
    magnitude         DECIMAL(4,3),             -- 0.000 – 1.000 (impact size)
    confidence        DECIMAL(4,3),             -- 0.000 – 1.000 (LLM self-reported)
    affected_sectors  JSON,                     -- ['energy', 'auto', ...] canonical sector keys
    affected_tickers  JSON,                     -- ['ONGC', 'BPCL', ...] NSE symbols
    validated_tickers JSON,                     -- subset of affected_tickers in our universe
    reasoning         TEXT,                     -- LLM chain-of-thought summary
    llm_provider      VARCHAR(30) NOT NULL,     -- 'gemini' / 'anthropic'
    llm_model         VARCHAR(100) NOT NULL,    -- specific model used
    tokens_in         INT,
    tokens_out        INT,
    cost_inr          DECIMAL(10,6),
    extracted_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (article_id) REFERENCES news_articles(id) ON DELETE CASCADE,
    UNIQUE KEY uk_article_model (article_id, llm_model),
    INDEX idx_theme_key (theme_key),
    INDEX idx_direction (direction),
    INDEX idx_extracted_at (extracted_at),
    INDEX idx_article (article_id)
) ENGINE=InnoDB CHARSET=utf8mb4;
