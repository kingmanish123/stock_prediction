# Setup Guide — Step-by-Step

Follow these steps **in order**. Don't skip. Each step has verification — run it before moving on.

Estimated total time: 60–90 minutes (first-time setup).

---

## Overview — what we'll set up

| # | Item | Type | Cost | Required |
|---|------|------|------|----------|
| 1 | Python 3.11+ | Runtime | Free | Must |
| 2 | Git | VCS | Free | Must |
| 3 | `uv` (package manager) | Tool | Free | Must |
| 4 | Project scaffolding | Local | Free | Must |
| 5 | Google Gemini API key | LLM (primary) | Free tier | Must |
| 6 | Anthropic Claude API key | LLM (reasoning) | Credits/coupon | Must |
| 7 | News source URLs (RSS + scrapers) | Config | Free | Must |
| 8 | NSE/BSE endpoints | Config | Free | Must |
| 9 | Reddit API (optional) | API | Free | Optional |
| 10 | MarketAux API (V2, defer) | Paid news | $29/mo | Skip for now |
| 11 | `.env` file | Config | — | Must |
| 12 | Verification test script | Code | — | Must |

---

## LLM Architecture Note

With both Gemini + Claude available, we'll use a **two-tier approach**:

| Task | LLM | Why |
|------|-----|-----|
| Bulk sentiment on all articles (~50–100/day) | **Gemini 1.5 Flash** | ~$0.075/M tokens — 40× cheaper than Claude Sonnet |
| Deep reasoning on top 15 predictions | **Claude Sonnet 4.6 or Opus 4.7** | Better at nuanced financial reasoning |

Estimated daily cost: **₹4–8 per run** (~₹100–200/month, offset by coupons).

---

## Step 1 — Verify Python & Git

### 1.1 Check Python version
```bash
python3 --version
```

**Expected output**: `Python 3.11.x` or `3.12.x` or `3.13.x`

**If output is 3.10 or older** (or command not found):
- **Mac**: Install via Homebrew: `brew install python@3.12`
- Verify: `python3.12 --version`

### 1.2 Check Git
```bash
git --version
```

**Expected**: `git version 2.x.x` (anything 2.x is fine)

**If not installed**:
- **Mac**: `brew install git` (or install Xcode Command Line Tools: `xcode-select --install`)

### 1.3 Record your versions
In `.env` or just for reference:
```
Python: <output of python3 --version>
Git: <output of git --version>
```

---

## Step 2 — Install `uv` (modern Python package manager)

`uv` is 10–100× faster than pip/poetry. Install:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

After install, **restart your terminal** OR run:
```bash
source $HOME/.cargo/env      # or whatever the installer told you
```

**Verify**:
```bash
uv --version
```

**Expected**: `uv 0.5.x` or newer.

---

## Step 3 — Initialize the project

```bash
cd /Users/apple/Documents/personal/Projects/Ideas/stock-prediction-system
uv init --python 3.12
```

This creates:
- `pyproject.toml` — project config
- `.python-version` — pins Python version
- `README.md` (may overwrite — say no or use different flag)

**If it asks to overwrite README.md — SAY NO** (our README has content).

```bash
# If README.md was overwritten, restore from git or re-create
# Then continue:
uv venv                      # creates .venv
source .venv/bin/activate    # activate virtual env
```

**Verify**:
```bash
which python
```

**Expected**: path inside `.venv/bin/python` (not system Python).

---

## Step 4 — Install dependencies

```bash
uv add pandas numpy pyarrow yfinance nsepy requests httpx beautifulsoup4 feedparser
uv add sentence-transformers transformers torch
uv add anthropic google-generativeai
uv add scikit-learn xgboost lightgbm ta
uv add rich tabulate
uv add sqlalchemy
uv add pyyaml python-dotenv pydantic tenacity click
uv add structlog
uv add jupyterlab matplotlib seaborn plotly
uv add --dev pytest pytest-cov ruff mypy
```

This will take a few minutes (torch is ~1 GB).

**Verify**:
```bash
python -c "import pandas, yfinance, xgboost, anthropic, google.generativeai; print('ALL OK')"
```

**Expected**: `ALL OK`

---

## Step 5 — Get Google Gemini API key

### 5.1 Sign in to Google AI Studio
URL: **https://aistudio.google.com/app/apikey**

- Sign in with your Google account (same one with coupon, if coupon is attached)
- Accept terms if prompted

### 5.2 Create API key
1. Click **"Create API key"** (top-left corner)
2. Select or create a Google Cloud project (you can pick an existing one or create new)
3. Key generated — starts with `AIza...`
4. **Copy it immediately** (you can view it again later, but copying now saves time)

### 5.3 Free tier limits (Gemini 1.5 Flash)
- 15 requests/minute (plenty for our use case)
- 1 million tokens/minute (way more than we need)
- 1,500 requests/day (more than enough — we use ~50/day)
- **Cost after free tier**: $0.075/M input tokens, $0.30/M output tokens

### 5.4 Save the key
Don't paste anywhere yet — we'll put it in `.env` in Step 11.
Just keep it copied or in a password manager for now.

**Format to save**:
```
GEMINI_API_KEY=AIza...
```

---

## Step 6 — Get Anthropic Claude API key

### 6.1 Sign in to Anthropic Console
URL: **https://console.anthropic.com**

- Sign in (use the account with the coupon)
- If new: verify email + phone

### 6.2 Apply coupon (if not already applied)
1. Go to **Settings → Billing**
2. Check "Promotional Credits" — if coupon shows up as pending, apply it
3. If coupon needs a code, use **Redeem code** option

### 6.3 Create API key
1. Go to **API Keys** (left sidebar) — URL: https://console.anthropic.com/settings/keys
2. Click **"Create Key"**
3. Name it: `stock-prediction-system-local`
4. Key generated — starts with `sk-ant-api03-...`
5. **Copy immediately** — Anthropic shows the key ONLY ONCE

### 6.4 Pricing (for reference)
- Claude Sonnet 4.6: ~$3/M input, $15/M output
- Claude Opus 4.7: ~$15/M input, $75/M output
- For our use case (~15 deep reasoning calls/day × 2K tokens), Sonnet is plenty → ~$0.09/day = ~₹8/day

### 6.5 Save the key

**Format to save**:
```
ANTHROPIC_API_KEY=sk-ant-api03-...
```

---

## Step 7 — News sources (no signup needed)

All of these are free, no accounts required. Just config URLs.

### 7.1 NSE (National Stock Exchange)
- **Corporate announcements**: `https://www.nseindia.com/api/corporate-announcements?index=equities`
- **Note**: NSE requires specific headers (User-Agent + Cookie) to access APIs. We'll handle this in code.
- **Verification**: open `https://www.nseindia.com/companies-listing/corporate-filings-announcements` in your browser — if it loads, you're good.

### 7.2 BSE (Bombay Stock Exchange)
- **Corporate announcements**: `https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w`
- **Verification**: open `https://www.bseindia.com/corporates/ann.html` in your browser.

### 7.3 RSS feeds (free, no signup)
```
MoneyControl markets:        https://www.moneycontrol.com/rss/buzzingstocks.xml
MoneyControl business:       https://www.moneycontrol.com/rss/business.xml
Economic Times markets:      https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms
Economic Times stocks:       https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms
LiveMint markets:            https://www.livemint.com/rss/markets
Business Standard markets:   https://www.business-standard.com/rss/markets-106.rss
```

**Verification**: open any URL in browser — if XML shows, feed works.

### 7.4 Yahoo Finance news (via yfinance)
No URL needed — Python library fetches per ticker:
```python
import yfinance as yf
news = yf.Ticker("RELIANCE.NS").news
```

---

## Step 8 — Market data (no signup needed)

### 8.1 yfinance
- Free, no API key, no signup
- Works via Yahoo Finance backend
- Indian stocks: use `.NS` suffix (e.g., `RELIANCE.NS`)

**Verification** (run after Step 4 deps are installed):
```bash
python -c "import yfinance as yf; print(yf.Ticker('RELIANCE.NS').history(period='5d'))"
```

### 8.2 nsepy
- Free, no signup
- Direct from NSE
- Sometimes breaks when NSE changes internal APIs — we'll handle with fallbacks

**Verification**:
```bash
python -c "from nsepy import get_history; from datetime import date, timedelta; print(get_history('RELIANCE', start=date.today() - timedelta(days=7), end=date.today()))"
```

---

## Step 9 — Reddit API (OPTIONAL — skip for V1)

Only do this if you want to include Reddit sentiment (r/IndianStockMarket, r/IndianStreetBets). It's noisy; recommended SKIP for V1.

If you want to set it up anyway:
1. Go to **https://www.reddit.com/prefs/apps**
2. Click **"Create another app"**
3. Type: **script** (for personal use)
4. Name: `stock-prediction-system`
5. Redirect URI: `http://localhost:8080` (not used but required)
6. After creation, save:
   - `client_id` (below the app name)
   - `client_secret`
   - Your Reddit username + password

---

## Step 10 — MarketAux (DEFER to V2)

**Skip for now**. Revisit only if V1 shows weak news coverage.

When you're ready:
1. Go to **https://www.marketaux.com**
2. Sign up → Dashboard → API token
3. $29/month plan has financial news aggregation with pre-tagged entities

---

## Step 11 — Create `.env` file

Create `.env` in project root:

```bash
cd /Users/apple/Documents/personal/Projects/Ideas/stock-prediction-system
touch .env
```

Open in your editor and paste this template — then replace placeholders:

```env
# ─── LLM Configuration ───────────────────────────────
GEMINI_API_KEY=AIza_YOUR_GEMINI_KEY_HERE
ANTHROPIC_API_KEY=sk-ant-api03_YOUR_CLAUDE_KEY_HERE

# Which model to use for bulk NLP (sentiment, classification)
LLM_BULK_PROVIDER=gemini
LLM_BULK_MODEL=gemini-1.5-flash

# Which model to use for deep reasoning (top predictions)
LLM_REASONING_PROVIDER=anthropic
LLM_REASONING_MODEL=claude-sonnet-4-6

# ─── Paths ───────────────────────────────────────────
DATA_DIR=./data
REPORTS_DIR=./reports
PREDICTIONS_DIR=./predictions
LOGS_DIR=./logs
MODELS_DIR=./models

# ─── Database ────────────────────────────────────────
DB_PATH=./data/system.sqlite

# ─── Logging ─────────────────────────────────────────
LOG_LEVEL=INFO

# ─── News sources toggle (all free by default) ───────
ENABLE_NSE_ANNOUNCEMENTS=true
ENABLE_BSE_ANNOUNCEMENTS=true
ENABLE_MONEYCONTROL_RSS=true
ENABLE_ET_RSS=true
ENABLE_LIVEMINT_RSS=true
ENABLE_BUSINESS_STANDARD_RSS=true
ENABLE_YAHOO_FINANCE_NEWS=true

# V2 paid news (leave empty / false for V1)
ENABLE_MARKETAUX=false
MARKETAUX_API_KEY=

# Reddit (leave empty for V1)
ENABLE_REDDIT=false
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=
REDDIT_PASSWORD=

# ─── Market data ─────────────────────────────────────
UNIVERSE=NIFTY50                # future: NIFTY100, NIFTY500

# ─── Run configuration ───────────────────────────────
PRE_MARKET_RUN_TIME=08:00
POST_MARKET_RUN_TIME=16:00
TIMEZONE=Asia/Kolkata

# ─── Cost control ────────────────────────────────────
DAILY_LLM_BUDGET_INR=20         # soft cap, alert if exceeded
MAX_DEEP_REASONING_CALLS=15     # top N predictions get Claude reasoning
```

Also create `.gitignore` if not present:
```bash
cat > .gitignore << 'EOF'
.env
.venv/
data/
reports/
predictions/
logs/
models/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
.ipynb_checkpoints/
*.sqlite
*.parquet
EOF
```

---

## Step 12 — Verification test script

Create `test_setup.py` in project root:

```python
"""Quick test to verify all APIs + libraries work."""
import os
from dotenv import load_dotenv

load_dotenv()

# 1. Test Gemini
print("1. Testing Gemini...")
try:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-1.5-flash")
    resp = model.generate_content("Reply with exactly: GEMINI_OK")
    print(f"   ✓ Gemini: {resp.text.strip()}")
except Exception as e:
    print(f"   ✗ Gemini FAILED: {e}")

# 2. Test Claude
print("2. Testing Claude...")
try:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=20,
        messages=[{"role": "user", "content": "Reply with exactly: CLAUDE_OK"}]
    )
    print(f"   ✓ Claude: {resp.content[0].text.strip()}")
except Exception as e:
    print(f"   ✗ Claude FAILED: {e}")

# 3. Test yfinance
print("3. Testing yfinance...")
try:
    import yfinance as yf
    data = yf.Ticker("RELIANCE.NS").history(period="5d")
    print(f"   ✓ yfinance: fetched {len(data)} rows for RELIANCE.NS")
except Exception as e:
    print(f"   ✗ yfinance FAILED: {e}")

# 4. Test nsepy
print("4. Testing nsepy...")
try:
    from nsepy import get_history
    from datetime import date, timedelta
    data = get_history("RELIANCE", start=date.today() - timedelta(days=7), end=date.today())
    print(f"   ✓ nsepy: fetched {len(data)} rows")
except Exception as e:
    print(f"   ✗ nsepy FAILED (sometimes NSE breaks this — ok if yfinance worked): {e}")

# 5. Test RSS
print("5. Testing RSS feed...")
try:
    import feedparser
    feed = feedparser.parse("https://www.moneycontrol.com/rss/buzzingstocks.xml")
    print(f"   ✓ RSS: fetched {len(feed.entries)} articles from MoneyControl")
except Exception as e:
    print(f"   ✗ RSS FAILED: {e}")

# 6. Test XGBoost
print("6. Testing XGBoost...")
try:
    import xgboost as xgb
    print(f"   ✓ XGBoost version {xgb.__version__}")
except Exception as e:
    print(f"   ✗ XGBoost FAILED: {e}")

# 7. Test Rich (terminal output)
print("7. Testing Rich...")
try:
    from rich.console import Console
    Console().print("   ✓ [bold green]Rich works[/bold green]")
except Exception as e:
    print(f"   ✗ Rich FAILED: {e}")

print("\nSetup verification complete. All ✓ means you're ready to build.")
```

**Run**:
```bash
python test_setup.py
```

**Expected output**: all 7 checks with ✓ marks.

---

## Security reminders

- ❌ **Never commit `.env`** — already in `.gitignore`
- ❌ **Never paste API keys in public channels** (Slack, Discord, GitHub issues)
- ✅ **Regenerate any key that leaks immediately** in the provider console
- ✅ **Use separate keys per project** if possible
- ✅ **Monitor usage** — Gemini Studio + Anthropic Console both have dashboards

---

## If something fails

Go back to the failing step. Common issues:

| Issue | Fix |
|-------|-----|
| `uv: command not found` | Restart terminal after `uv` install, or source shell profile |
| `Python 3.10 only available` | Install 3.12: `brew install python@3.12`, reinit venv |
| `Gemini 401` | Check key copied correctly, project is enabled |
| `Anthropic 401` | Check coupon was applied before creating key |
| `yfinance SSL error` | Usually transient — retry. Or update: `uv add yfinance --upgrade` |
| `nsepy 403` | NSE changed API — fall back to yfinance/scraping |
| `torch install 2 GB download` | Expected — let it finish |

---

## Completion checklist

- [ ] Step 1: Python 3.11+ verified
- [ ] Step 2: `uv` installed, `uv --version` works
- [ ] Step 3: Project initialized with venv
- [ ] Step 4: All deps installed, `python -c "import ..."` succeeds
- [ ] Step 5: Gemini API key created
- [ ] Step 6: Claude API key created, coupon applied
- [ ] Step 7–8: News + market sources verified via browser/test
- [ ] Step 11: `.env` file created with all keys
- [ ] Step 12: `test_setup.py` shows all ✓

When all boxes ticked → ready to start Week 2 (data ingestion coding).
