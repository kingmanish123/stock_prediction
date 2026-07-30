"""Feature assembler — loads data from MySQL and produces the feature matrix.

The feature matrix has one row per (stock_id, trade_date) and columns for every
feature category. It's stored as Parquet for fast ML training loads.

Key design: features for `trade_date` use data STRICTLY BEFORE that date.
This prevents look-ahead bias. Indicators are computed on the trailing series
and we select the row at trade_date.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from ..common import config
from ..common.config import DATA_DIR
from ..common.logger import get_logger
from ..db.models import MarketDataDaily, Stock, StockUniverseHistory
from ..db.session import get_session
from .calendar_features import (
    EARNINGS_FEATURE_COLS,
    TEMPORAL_FEATURE_COLS,
    add_temporal_features,
    load_earnings_proximity,
)
from .market_context import (
    MARKET_CONTEXT_FEATURE_COLS,
    load_market_context,
)
from .momentum import MOMENTUM_FEATURE_COLS, add_momentum_features
from .technical import TECHNICAL_FEATURE_COLS, add_technical_features
from .volatility import VOLATILITY_FEATURE_COLS, add_volatility_features
from .volume import VOLUME_FEATURE_COLS, add_volume_features

logger = get_logger(__name__)


# Minimum calendar-days lookback to ensure all rolling indicators have data.
# Longest window we compute is vol_regime = 252-day rolling rank of 20-day vol,
# so we need 272+ trading days. 400 calendar days ≈ 275 trading days, then
# multiplied by 1.6 = 640 calendar days ≈ 440 trading days (comfortable).
MIN_LOOKBACK_DAYS = 400


ALL_STOCK_FEATURE_COLS: list[str] = (
    TECHNICAL_FEATURE_COLS
    + MOMENTUM_FEATURE_COLS
    + VOLATILITY_FEATURE_COLS
    + VOLUME_FEATURE_COLS
)

ALL_FEATURE_COLS: list[str] = (
    ALL_STOCK_FEATURE_COLS
    + MARKET_CONTEXT_FEATURE_COLS
    + TEMPORAL_FEATURE_COLS
    + EARNINGS_FEATURE_COLS
)


def _get_active_stocks_in_universe(as_of_date: date) -> list[Stock]:
    """Active universe members at the given date (survivorship-bias-free)."""
    universe_name = config.UNIVERSE
    with get_session() as s:
        stocks = s.scalars(
            select(Stock)
            .join(StockUniverseHistory, StockUniverseHistory.stock_id == Stock.id)
            .where(
                StockUniverseHistory.universe_name == universe_name,
                StockUniverseHistory.valid_from <= as_of_date,
                (StockUniverseHistory.valid_to.is_(None))
                | (StockUniverseHistory.valid_to > as_of_date),
            )
            .order_by(Stock.symbol)
        ).all()
        for x in stocks:
            s.expunge(x)
        return list(stocks)


def _load_stock_ohlcv(stock_id: int, start: date, end: date) -> pd.DataFrame:
    """Load OHLCV for one stock into a date-indexed DataFrame."""
    with get_session() as s:
        rows = s.execute(
            select(
                MarketDataDaily.trade_date,
                MarketDataDaily.open,
                MarketDataDaily.high,
                MarketDataDaily.low,
                MarketDataDaily.close,
                MarketDataDaily.adjusted_close,
                MarketDataDaily.volume,
                MarketDataDaily.turnover_cr,
            )
            .where(
                MarketDataDaily.stock_id == stock_id,
                MarketDataDaily.trade_date >= start,
                MarketDataDaily.trade_date <= end,
            )
            .order_by(MarketDataDaily.trade_date)
        ).all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        rows,
        columns=["trade_date", "open", "high", "low", "close", "adjusted_close", "volume", "turnover_cr"],
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index("trade_date").sort_index()
    # Convert Decimal to float for numpy ops
    for col in ["open", "high", "low", "close", "adjusted_close", "turnover_cr"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].fillna(0).astype(int)
    return df


def build_feature_matrix(
    start_date: date,
    end_date: date,
    write_parquet: bool = True,
) -> pd.DataFrame:
    """Build features for every (stock, date) pair in the window.

    Returns a long-format DataFrame: rows = (stock_id × trade_date),
    columns = all feature names.
    """
    lookback_start = start_date - timedelta(days=int(MIN_LOOKBACK_DAYS * 1.6))  # buffer for non-trading days
    logger.info("feature_build_start", start=str(start_date), end=str(end_date))

    # 1. Market context (shared across all stocks) ───────────────────
    logger.info("loading_market_context")
    market_ctx = load_market_context(start_date, end_date)
    logger.info("market_context_loaded", rows=len(market_ctx), cols=len(market_ctx.columns))

    # Nifty 50 benchmark for relative strength
    nifty_close = None
    with get_session() as s:
        from ..db.models import GlobalIndexDaily
        rows = s.execute(
            select(GlobalIndexDaily.trade_date, GlobalIndexDaily.close)
            .where(
                GlobalIndexDaily.index_symbol == "^NSEI",
                GlobalIndexDaily.trade_date >= lookback_start,
                GlobalIndexDaily.trade_date <= end_date,
            )
            .order_by(GlobalIndexDaily.trade_date)
        ).all()
    if rows:
        bench_df = pd.DataFrame(rows, columns=["date", "close"])
        bench_df["date"] = pd.to_datetime(bench_df["date"])
        nifty_close = bench_df.set_index("date")["close"].astype(float)

    # 2. Stock universe at start date (or use current Nifty 50 for simplicity)
    stocks = _get_active_stocks_in_universe(end_date)
    stock_ids = [s.id for s in stocks]
    logger.info("stocks_in_universe", count=len(stocks))

    # 3. Earnings proximity (per stock × date) ───────────────────────
    logger.info("loading_earnings_proximity")
    earnings_df = load_earnings_proximity(stock_ids, start_date, end_date)
    earnings_df["trade_date"] = pd.to_datetime(earnings_df["trade_date"])

    # 4. Per-stock feature computation ────────────────────────────────
    # MACD-26 + signal-9 need ≥ 35 rows. Skip recent IPOs / thinly traded stocks.
    MIN_ROWS_FOR_FEATURES = 60
    all_frames: list[pd.DataFrame] = []
    skipped_thin = 0
    for stock in stocks:
        ohlcv = _load_stock_ohlcv(stock.id, lookback_start, end_date)
        if ohlcv.empty:
            logger.warning("stock_no_data", stock_id=stock.id, symbol=stock.symbol)
            continue
        if len(ohlcv) < MIN_ROWS_FOR_FEATURES:
            skipped_thin += 1
            continue

        # Compute indicators on full series
        ohlcv = add_technical_features(ohlcv)
        ohlcv = add_momentum_features(ohlcv, benchmark_close=nifty_close)
        ohlcv = add_volatility_features(ohlcv)
        ohlcv = add_volume_features(ohlcv)

        # Filter to requested window
        features_slice = ohlcv.loc[
            ohlcv.index >= pd.Timestamp(start_date)
        ][ALL_STOCK_FEATURE_COLS].copy()
        features_slice["stock_id"] = stock.id
        features_slice["symbol"] = stock.symbol
        features_slice["trade_date"] = features_slice.index

        all_frames.append(features_slice.reset_index(drop=True))

    if not all_frames:
        logger.warning("no_features_built")
        return pd.DataFrame()

    features = pd.concat(all_frames, ignore_index=True)
    logger.info(
        "per_stock_features_done",
        rows=len(features),
        skipped_thin_history=skipped_thin,
    )

    # 5. Join market context (broadcast by date) ─────────────────────
    market_ctx_reset = market_ctx.reset_index().rename(columns={"date": "trade_date"})
    features = features.merge(market_ctx_reset, on="trade_date", how="left")

    # 6. Join earnings proximity ──────────────────────────────────────
    if not earnings_df.empty:
        features = features.merge(
            earnings_df[["stock_id", "trade_date"] + EARNINGS_FEATURE_COLS],
            on=["stock_id", "trade_date"],
            how="left",
        )
        features["days_to_earnings"] = features["days_to_earnings"].fillna(999).astype(int)
        features["is_earnings_day"] = features["is_earnings_day"].fillna(0).astype(int)
    else:
        features["days_to_earnings"] = 999
        features["is_earnings_day"] = 0

    # 7. Temporal features ────────────────────────────────────────────
    features_with_temporal = features.set_index("trade_date")
    features_with_temporal = add_temporal_features(features_with_temporal)
    features = features_with_temporal.reset_index()

    # Rearrange columns: identifiers first
    ordered_cols = ["trade_date", "stock_id", "symbol"] + [
        c for c in features.columns if c not in {"trade_date", "stock_id", "symbol"}
    ]
    features = features[ordered_cols]

    logger.info(
        "feature_matrix_built",
        rows=len(features),
        cols=len(features.columns),
        stocks=features["stock_id"].nunique(),
        dates=features["trade_date"].nunique(),
    )

    # 8. Write Parquet ────────────────────────────────────────────────
    if write_parquet:
        out_dir: Path = DATA_DIR / "features"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"features_{start_date}_{end_date}.parquet"
        features.to_parquet(out_path, index=False)
        logger.info("features_written", path=str(out_path))

    return features
