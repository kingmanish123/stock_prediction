-- ─────────────────────────────────────────────────────────────────────
--  Upstox broker integration — add instrument_key column to stocks
--  Upstox uses ISIN-based keys like 'NSE_EQ|INE009A01021' for API calls.
-- ─────────────────────────────────────────────────────────────────────

SET NAMES utf8mb4;

ALTER TABLE stocks
    ADD COLUMN upstox_instrument_key VARCHAR(100) DEFAULT NULL
        AFTER yfinance_ticker;

ALTER TABLE stocks
    ADD INDEX idx_upstox_key (upstox_instrument_key);
