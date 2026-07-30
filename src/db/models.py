"""SQLAlchemy ORM models matching migrations/001_initial_schema.sql.

Keep this file in sync with the SQL schema. When adding/changing columns,
update both the SQL migration and this file.
"""
from datetime import date, datetime, time as dtime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from sqlalchemy.dialects.mysql import LONGTEXT, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


def _enum_col(enum_cls: type, name: str) -> SQLEnum:
    """SQLEnum configured to read/write by .value (matching MySQL ENUM literal)."""
    return SQLEnum(
        enum_cls,
        name=name,
        values_callable=lambda x: [e.value for e in x],
    )


# ─── Enums ──────────────────────────────────────────────────────────


class SentimentLabel(str, Enum):
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"


class ExtractionMethod(str, Enum):
    RULE_BASED = "rule_based"
    NER = "ner"
    LLM = "llm"
    MANUAL = "manual"


class EventType(str, Enum):
    EARNINGS_ANNOUNCEMENT = "earnings_announcement"
    BOARD_MEETING = "board_meeting"
    DIVIDEND = "dividend"
    BONUS = "bonus"
    SPLIT = "split"
    RIGHTS_ISSUE = "rights_issue"
    BUYBACK = "buyback"
    MERGER = "merger"
    ACQUISITION = "acquisition"
    MANAGEMENT_CHANGE = "management_change"
    CREDIT_RATING = "credit_rating"
    REGULATORY = "regulatory"
    OTHER = "other"


class EventStatus(str, Enum):
    UPCOMING = "upcoming"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RunType(str, Enum):
    PREDICTION = "prediction"
    VALIDATION = "validation"
    BACKFILL = "backfill"
    TRAINING = "training"
    EXPERIMENT = "experiment"


class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class PredictionDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class ThemeDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


# ─── Models ─────────────────────────────────────────────────────────


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    nse_symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    bse_code: Mapped[str | None] = mapped_column(String(20), unique=True)
    isin: Mapped[str | None] = mapped_column(String(20), unique=True)
    yfinance_ticker: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    upstox_instrument_key: Mapped[str | None] = mapped_column(String(100))
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    market_cap_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    currently_active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_date: Mapped[date | None] = mapped_column(Date)
    delisted_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    market_data = relationship("MarketDataDaily", back_populates="stock")
    universe_rows = relationship("StockUniverseHistory", back_populates="stock")
    events = relationship("CorporateEvent", back_populates="stock")
    predictions = relationship("Prediction", back_populates="stock")


class StockUniverseHistory(Base):
    __tablename__ = "stock_universe_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    universe_name: Mapped[str] = mapped_column(String(30), nullable=False)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    rebalance_event: Mapped[str | None] = mapped_column(String(50))
    change_reason: Mapped[str | None] = mapped_column(String(255))
    announcement_url: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    stock = relationship("Stock", back_populates="universe_rows")

    __table_args__ = (
        UniqueConstraint("universe_name", "stock_id", "valid_from", name="uk_no_overlap"),
    )


class MarketDataDaily(Base):
    __tablename__ = "market_data_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    turnover_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    num_trades: Mapped[int | None] = mapped_column(Integer)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    delivery_qty: Mapped[int | None] = mapped_column(BigInteger)
    delivery_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    data_source: Mapped[str] = mapped_column(String(20), default="yfinance")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    stock = relationship("Stock", back_populates="market_data")

    __table_args__ = (
        UniqueConstraint("stock_id", "trade_date", name="uk_stock_date"),
    )


class GlobalIndexDaily(Base):
    __tablename__ = "global_indices_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    index_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    index_name: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str | None] = mapped_column(String(10))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(15, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    daily_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("index_symbol", "trade_date", name="uk_index_date"),
    )


class MacroDataDaily(Base):
    __tablename__ = "macro_data_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    indicator_code: Mapped[str] = mapped_column(String(50), nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    unit: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("indicator_code", "observation_date", name="uk_indicator_date"),
    )


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_article_id: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(LONGTEXT)
    author: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    language: Mapped[str] = mapped_column(String(10), default="en")
    content_hash: Mapped[str | None] = mapped_column(CHAR(64))
    sentiment_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    sentiment_label: Mapped[SentimentLabel | None] = mapped_column(
        _enum_col(SentimentLabel, "sentiment_label")
    )
    event_type: Mapped[str | None] = mapped_column(String(50))
    impact_magnitude: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    llm_analysis: Mapped[dict | None] = mapped_column(MySQLJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tickers = relationship("ArticleTicker", back_populates="article", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source", "source_article_id", name="uk_source_article"),
        UniqueConstraint("content_hash", name="uk_content_hash"),
    )


class NewsTheme(Base):
    __tablename__ = "news_themes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False
    )
    theme_key: Mapped[str | None] = mapped_column(String(50))
    theme_label: Mapped[str | None] = mapped_column(String(300))
    direction: Mapped[ThemeDirection | None] = mapped_column(
        _enum_col(ThemeDirection, "theme_direction")
    )
    magnitude: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    affected_sectors: Mapped[list | None] = mapped_column(MySQLJSON)
    affected_tickers: Mapped[list | None] = mapped_column(MySQLJSON)
    validated_tickers: Mapped[list | None] = mapped_column(MySQLJSON)
    reasoning: Mapped[str | None] = mapped_column(Text)
    llm_provider: Mapped[str] = mapped_column(String(30), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    article = relationship("NewsArticle")

    __table_args__ = (
        UniqueConstraint("article_id", "llm_model", name="uk_article_model"),
    )


class ArticleTicker(Base):
    __tablename__ = "article_tickers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    mention_confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=1.000)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        _enum_col(ExtractionMethod, "extraction_method"), default=ExtractionMethod.RULE_BASED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    article = relationship("NewsArticle", back_populates="tickers")
    stock = relationship("Stock")

    __table_args__ = (
        UniqueConstraint("article_id", "stock_id", name="uk_article_stock"),
    )


class CorporateEvent(Base):
    __tablename__ = "corporate_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    event_type: Mapped[EventType] = mapped_column(_enum_col(EventType, "event_type"), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_time: Mapped[dtime | None] = mapped_column(Time)
    status: Mapped[EventStatus] = mapped_column(
        _enum_col(EventStatus, "event_status"), default=EventStatus.UPCOMING
    )
    title: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))
    source_id: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict | None] = mapped_column("metadata", MySQLJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    stock = relationship("Stock", back_populates="events")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_type: Mapped[RunType] = mapped_column(_enum_col(RunType, "run_type"), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[RunStatus] = mapped_column(
        _enum_col(RunStatus, "run_status"), default=RunStatus.RUNNING
    )
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    articles_fetched: Mapped[int] = mapped_column(Integer, default=0)
    articles_processed: Mapped[int] = mapped_column(Integer, default=0)
    stocks_processed: Mapped[int] = mapped_column(Integer, default=0)
    predictions_count: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls_gemini: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls_claude: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_inr: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    error_log: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", MySQLJSON)


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    direction: Mapped[PredictionDirection] = mapped_column(
        _enum_col(PredictionDirection, "prediction_direction"), nullable=False
    )
    predicted_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    predicted_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    predicted_close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    predicted_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    buy_rank: Mapped[int | None] = mapped_column(TINYINT)
    sell_rank: Mapped[int | None] = mapped_column(TINYINT)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    features_snapshot: Mapped[dict | None] = mapped_column(MySQLJSON)
    model_outputs: Mapped[dict | None] = mapped_column(MySQLJSON)
    reasoning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run = relationship("Run")
    stock = relationship("Stock", back_populates="predictions")
    validation = relationship("Validation", back_populates="prediction", uselist=False)

    __table_args__ = (
        UniqueConstraint("run_date", "stock_id", name="uk_run_date_stock"),
    )


class Validation(Base):
    __tablename__ = "validations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    actual_open: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    actual_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    actual_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    actual_close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    actual_volume: Mapped[int | None] = mapped_column(BigInteger)
    actual_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    direction_correct: Mapped[bool | None] = mapped_column(Boolean)
    range_hit: Mapped[bool | None] = mapped_column(Boolean)
    range_overlap_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    validated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    prediction = relationship("Prediction", back_populates="validation")


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    algorithm: Mapped[str | None] = mapped_column(String(50))
    trained_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    training_data_from: Mapped[date | None] = mapped_column(Date)
    training_data_to: Mapped[date | None] = mapped_column(Date)
    num_training_samples: Mapped[int | None] = mapped_column(Integer)
    features_used: Mapped[dict | None] = mapped_column(MySQLJSON)
    hyperparameters: Mapped[dict | None] = mapped_column(MySQLJSON)
    validation_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    validation_precision: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    validation_recall: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    validation_f1: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    validation_sharpe: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    validation_metrics: Mapped[dict | None] = mapped_column(MySQLJSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime)
    file_path: Mapped[str | None] = mapped_column(String(500))
    feature_importance: Mapped[dict | None] = mapped_column(MySQLJSON)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("model_name", "version", name="uk_model_version"),
    )


class ApiCost(Base):
    __tablename__ = "api_costs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    service: Mapped[str] = mapped_column(String(50), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    called_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StockFundamentals(Base):
    __tablename__ = "stock_fundamentals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    pe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    forward_pe: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    pb_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    ps_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    peg_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    ev_to_ebitda: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))

    market_cap_cr: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger)
    float_shares: Mapped[int | None] = mapped_column(BigInteger)

    profit_margin: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    operating_margin: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    roe: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    roa: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    revenue_growth_yoy: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    earnings_growth_yoy: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    quarterly_earnings_growth: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    debt_to_equity: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    current_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    total_cash_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    total_debt_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))

    dividend_yield: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    payout_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fifty_two_week_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fifty_two_week_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    beta: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))

    data_source: Mapped[str] = mapped_column(String(30), default="yfinance")
    raw_json: Mapped[dict | None] = mapped_column(MySQLJSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("stock_id", "snapshot_date", name="uk_stock_snapshot"),
    )


class AlgoExperiment(Base):
    __tablename__ = "algo_experiments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    algo_name: Mapped[str] = mapped_column(String(100), nullable=False)
    algo_version: Mapped[str] = mapped_column(String(50), nullable=False)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    trading_days_covered: Mapped[int | None] = mapped_column(Integer)

    config_json: Mapped[dict | None] = mapped_column(MySQLJSON)

    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    direction_correct: Mapped[int] = mapped_column(Integer, default=0)
    direction_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))

    target_hits: Mapped[int] = mapped_column(Integer, default=0)
    stop_hits: Mapped[int] = mapped_column(Integer, default=0)
    holds: Mapped[int] = mapped_column(Integer, default=0)
    skipped_gap: Mapped[int] = mapped_column(Integer, default=0)

    total_pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    avg_pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))

    max_drawdown_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    best_trade_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    worst_trade_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    per_day_results: Mapped[list | None] = mapped_column(MySQLJSON)

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "algo_name", "algo_version", "start_date", "end_date",
            name="uk_algo_version_window",
        ),
    )


class DailyMetric(Base):
    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    total_predictions: Mapped[int | None] = mapped_column(Integer)
    direction_correct_count: Mapped[int | None] = mapped_column(Integer)
    direction_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    top5_buy_correct: Mapped[int | None] = mapped_column(TINYINT)
    top5_sell_correct: Mapped[int | None] = mapped_column(TINYINT)
    top5_buy_avg_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    top5_sell_avg_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    range_hit_count: Mapped[int | None] = mapped_column(Integer)
    range_hit_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    rolling_30d_direction_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    rolling_30d_top5_buy_hit_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    rolling_30d_top5_sell_hit_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    rolling_30d_simulated_return: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    run_duration_sec: Mapped[int | None] = mapped_column(Integer)
    articles_count: Mapped[int | None] = mapped_column(Integer)
    total_cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
