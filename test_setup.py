"""Verification script — checks all APIs + libraries work.

Run with:
    python test_setup.py

Expected: all 7 checks should show ✓. Missing API keys show ⚠️.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

results = []


def check(name: str, fn):
    try:
        msg = fn()
        results.append((name, "ok", msg))
        print(f"  ✓ {name}: {msg}")
    except Exception as e:
        results.append((name, "fail", str(e)))
        print(f"  ✗ {name} FAILED: {e}")


def warn(name: str, msg: str):
    results.append((name, "warn", msg))
    print(f"  ⚠️  {name}: {msg}")


print("─" * 60)
print("  STOCK PREDICTION SYSTEM — SETUP VERIFICATION")
print("─" * 60)

# 1. Gemini
print("\n[1] Testing Google Gemini API...")
gemini_key = os.getenv("GEMINI_API_KEY", "")
if not gemini_key or "YOUR_GEMINI_KEY" in gemini_key:
    warn("Gemini", "GEMINI_API_KEY not set in .env (skipping)")
else:
    def test_gemini():
        from google import genai
        model_name = os.getenv("LLM_BULK_MODEL", "gemini-2.5-flash")
        client = genai.Client(api_key=gemini_key)
        resp = client.models.generate_content(
            model=model_name,
            contents="Reply with exactly: GEMINI_OK",
        )
        return f"{resp.text.strip()} (model: {model_name})"
    check("Gemini", test_gemini)

# 2. Claude
print("\n[2] Testing Anthropic Claude API...")
claude_key = os.getenv("ANTHROPIC_API_KEY", "")
if not claude_key or "YOUR_CLAUDE_KEY" in claude_key:
    warn("Claude", "ANTHROPIC_API_KEY not set in .env (skipping)")
else:
    def test_claude():
        from anthropic import Anthropic
        client = Anthropic(api_key=claude_key)
        model_name = os.getenv("LLM_REASONING_MODEL", "claude-sonnet-4-6")
        resp = client.messages.create(
            model=model_name,
            max_tokens=20,
            messages=[{"role": "user", "content": "Reply with exactly: CLAUDE_OK"}]
        )
        return resp.content[0].text.strip()
    check("Claude", test_claude)

# 3. yfinance
print("\n[3] Testing yfinance (Indian stocks)...")
def test_yfinance():
    import yfinance as yf
    data = yf.Ticker("RELIANCE.NS").history(period="5d")
    if len(data) == 0:
        raise RuntimeError("No data returned")
    return f"fetched {len(data)} rows for RELIANCE.NS"
check("yfinance", test_yfinance)

# 4. RSS feed
print("\n[4] Testing RSS news feed...")
def test_rss():
    import feedparser
    feed = feedparser.parse("https://www.moneycontrol.com/rss/buzzingstocks.xml")
    if len(feed.entries) == 0:
        raise RuntimeError("Empty feed")
    return f"fetched {len(feed.entries)} articles from MoneyControl"
check("RSS feed", test_rss)

# 5. NSE announcements (direct API scrape)
print("\n[5] Testing NSE corporate announcements endpoint...")
def test_nse():
    import httpx
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(headers=headers, timeout=15.0, follow_redirects=True) as client:
        client.get("https://www.nseindia.com", headers=headers)
        url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return f"NSE returned {len(data)} announcements"
check("NSE API", test_nse)

# 6. XGBoost
print("\n[6] Testing XGBoost...")
def test_xgb():
    import xgboost as xgb
    return f"version {xgb.__version__}"
check("XGBoost", test_xgb)

# 7. Rich (terminal output)
print("\n[7] Testing Rich (terminal UI)...")
def test_rich():
    from rich.console import Console
    Console()
    return "works"
check("Rich", test_rich)

# 8. Finnhub
print("\n[8] Testing Finnhub API...")
finnhub_key = os.getenv("FINNHUB_API_KEY", "")
if not finnhub_key:
    warn("Finnhub", "FINNHUB_API_KEY not set (skipping)")
else:
    def test_finnhub():
        import finnhub
        client = finnhub.Client(api_key=finnhub_key)
        # Free tier: general news is available
        news = client.general_news("general", min_id=0)
        # Free tier: earnings calendar is available (try India-relevant dates)
        from datetime import date, timedelta
        today = date.today()
        next_week = today + timedelta(days=7)
        try:
            earnings = client.earnings_calendar(
                _from=str(today), to=str(next_week), symbol="", international=True
            )
            earn_count = len(earnings.get("earningsCalendar", []))
        except Exception:
            earn_count = 0
        return f"general_news: {len(news)} items, earnings_calendar: {earn_count} items"
    check("Finnhub", test_finnhub)

# 9. FRED
print("\n[9] Testing FRED API...")
fred_key = os.getenv("FRED_API_KEY", "")
if not fred_key:
    warn("FRED", "FRED_API_KEY not set (skipping)")
else:
    def test_fred():
        from fredapi import Fred
        fred = Fred(api_key=fred_key)
        # Fetch VIX (market volatility index) — last value
        vix = fred.get_series_latest_release("VIXCLS")
        latest = vix.iloc[-1] if len(vix) > 0 else None
        return f"VIX latest value: {latest:.2f}"
    check("FRED", test_fred)

# 10. MySQL via XAMPP
print("\n[10] Testing MySQL (XAMPP)...")
def test_mysql():
    import pymysql
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")

    # Connect to MySQL server (no database yet)
    conn = pymysql.connect(host=host, port=port, user=user, password=password)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            # Check/create database
            db_name = os.getenv("DB_NAME", "stock_prediction")
            cur.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.commit()
        return f"MySQL {version} connected; database '{db_name}' ready"
    finally:
        conn.close()
check("MySQL", test_mysql)

# Summary
print("\n" + "─" * 60)
ok_count = sum(1 for _, s, _ in results if s == "ok")
warn_count = sum(1 for _, s, _ in results if s == "warn")
fail_count = sum(1 for _, s, _ in results if s == "fail")

print(f"  Summary: {ok_count} ✓   {warn_count} ⚠️    {fail_count} ✗")
print("─" * 60)

if fail_count > 0:
    print("\n  Some checks FAILED. Review errors above.")
    sys.exit(1)
elif warn_count > 0:
    print("\n  Core libraries OK. Add API keys to .env to enable LLM checks.")
    sys.exit(0)
else:
    print("\n  All checks passed. Ready to build.")
    sys.exit(0)
