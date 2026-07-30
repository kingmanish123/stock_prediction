"""Centralized configuration loaded from .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _path(env_key: str, default: str) -> Path:
    raw = os.getenv(env_key, default).lstrip("./")
    p = PROJECT_ROOT / raw
    p.mkdir(parents=True, exist_ok=True)
    return p


# ─── Database ───────────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "stock_prediction")

DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)

# ─── LLM APIs ───────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

LLM_BULK_PROVIDER = os.getenv("LLM_BULK_PROVIDER", "gemini")
LLM_BULK_MODEL = os.getenv("LLM_BULK_MODEL", "gemini-2.5-flash")
LLM_REASONING_PROVIDER = os.getenv("LLM_REASONING_PROVIDER", "anthropic")
LLM_REASONING_MODEL = os.getenv("LLM_REASONING_MODEL", "claude-sonnet-4-6")

# ─── External data APIs ─────────────────────────────────────────────
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
MARKETAUX_API_KEY = os.getenv("MARKETAUX_API_KEY", "")

# ─── Upstox broker API (real-time market data) ──────────────────────
UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY", "")
UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET", "")
UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI", "http://localhost:8080/callback")
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")

# ─── News source toggles ────────────────────────────────────────────
ENABLE_NSE_ANNOUNCEMENTS = os.getenv("ENABLE_NSE_ANNOUNCEMENTS", "true").lower() == "true"
ENABLE_BSE_ANNOUNCEMENTS = os.getenv("ENABLE_BSE_ANNOUNCEMENTS", "true").lower() == "true"
ENABLE_MONEYCONTROL_RSS = os.getenv("ENABLE_MONEYCONTROL_RSS", "true").lower() == "true"
ENABLE_ET_RSS = os.getenv("ENABLE_ET_RSS", "true").lower() == "true"
ENABLE_LIVEMINT_RSS = os.getenv("ENABLE_LIVEMINT_RSS", "true").lower() == "true"
ENABLE_BUSINESS_STANDARD_RSS = os.getenv("ENABLE_BUSINESS_STANDARD_RSS", "true").lower() == "true"
ENABLE_YAHOO_FINANCE_NEWS = os.getenv("ENABLE_YAHOO_FINANCE_NEWS", "true").lower() == "true"
ENABLE_FINNHUB = os.getenv("ENABLE_FINNHUB", "true").lower() == "true"
ENABLE_MARKETAUX = os.getenv("ENABLE_MARKETAUX", "false").lower() == "true"
ENABLE_REDDIT = os.getenv("ENABLE_REDDIT", "false").lower() == "true"

# ─── Paths (auto-created) ───────────────────────────────────────────
DATA_DIR = _path("DATA_DIR", "data")
REPORTS_DIR = _path("REPORTS_DIR", "reports")
PREDICTIONS_DIR = _path("PREDICTIONS_DIR", "predictions")
LOGS_DIR = _path("LOGS_DIR", "logs")
MODELS_DIR = _path("MODELS_DIR", "models")

# ─── Run configuration ──────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
PRE_MARKET_RUN_TIME = os.getenv("PRE_MARKET_RUN_TIME", "08:00")
POST_MARKET_RUN_TIME = os.getenv("POST_MARKET_RUN_TIME", "16:00")
UNIVERSE = os.getenv("UNIVERSE", "NIFTY50")

# ─── Cost control ───────────────────────────────────────────────────
DAILY_LLM_BUDGET_INR = float(os.getenv("DAILY_LLM_BUDGET_INR", "20"))
MAX_DEEP_REASONING_CALLS = int(os.getenv("MAX_DEEP_REASONING_CALLS", "15"))
