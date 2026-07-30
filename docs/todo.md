# Running TODO — Pre-Market Stock Prediction System

Update daily. Focus on current week only.

---

## Blockers (resolve before Week 1 starts)
- [ ] Confirm LLM provider (Claude or OpenAI coupon?)
- [ ] Decide: rename folder to `stock-prediction-system/`? (not urgent)
- [ ] Confirm: Telegram push desired? (optional, 15 min setup)

## This week (Week 1: Apr 22 – Apr 28) — Setup
- [ ] Install Python 3.11+ (via pyenv if not installed)
- [ ] Install `uv` for dependency management (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [ ] Initialize project: `uv init && uv venv`
- [ ] Install core libs per [REQUIREMENTS.md §5.2](REQUIREMENTS.md#52-python-dependencies)
- [ ] Verify: `import pandas, yfinance, xgboost` — no errors
- [ ] Create `.env` from `.env.example`, add LLM API key
- [ ] Test LLM API: write minimal script that calls Claude/OpenAI once
- [ ] Test yfinance: download 5 days of RELIANCE.NS data
- [ ] Test nsepy: fetch NSE announcements for yesterday
- [ ] Create folder structure per [ARCHITECTURE.md §5](ARCHITECTURE.md#5-repository-structure)
- [ ] Initialize SQLite DB with schema from [ARCHITECTURE.md §4](ARCHITECTURE.md#4-data-model)

## Week 2 — Data Ingestion Layer
- [ ] Write `yfinance_client.py` — fetch OHLCV for Nifty 50 list
- [ ] Write `nse_bse.py` — scrape corporate announcements
- [ ] Write RSS fetchers: moneycontrol, economic_times, livemint
- [ ] Download 5 years of historical data (one-time bulk load)
- [ ] Test: one daily run produces cached Parquet + news JSON

## Week 3 — Feature Engineering
- [ ] Write technical indicator module (RSI, MACD, etc.)
- [ ] Write momentum features
- [ ] Write volatility + volume features
- [ ] Write global context features
- [ ] Assembler that produces daily features.parquet

## Week 4+ — see [ARCHITECTURE.md §10](ARCHITECTURE.md#10-phased-implementation-roadmap)

---

## Backlog (someday/maybe)
- [ ] FinBERT integration for fast sentiment
- [ ] Claude LLM deep reasoning layer
- [ ] XGBoost direction classifier
- [ ] Range regressor
- [ ] Ensemble voter
- [ ] Calibration
- [ ] Backtest harness
- [ ] Validation module
- [ ] Rich terminal output
- [ ] Markdown report writer
- [ ] Telegram bot integration (optional)
- [ ] Weekly retraining script
- [ ] Research notebooks (experiment framework)

## Reading backlog
- [ ] "Algorithmic Trading" Ernie Chan (still useful for quant mindset)
- [ ] "Advances in Financial ML" Marcos López de Prado (ML pitfalls in finance)
- [ ] Paper: "Time Series Momentum" (Moskowitz et al.) — momentum factor evidence
- [ ] Zerodha Varsity: Trading Psychology module
