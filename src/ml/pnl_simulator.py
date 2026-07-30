"""Simulate daily trading P&L from predicted top-N picks.

Assumption: equal-weight portfolio. For each trading day in the test window:
  - Pick top N stocks by probability (or rank)
  - Entry: next day's OPEN price
  - Exit: next day's CLOSE price
  - Per-stock return = (close - open) / open
  - Portfolio daily return = simple average of N returns

Reports: equity curve, Sharpe ratio, max drawdown, win rate, hit rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select

from ..common.logger import get_logger
from ..db.models import MarketDataDaily
from ..db.session import get_session

logger = get_logger(__name__)


@dataclass
class SimulationResult:
    n_days: int
    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float              # % of days with positive portfolio return
    hit_rate: float              # avg % of daily top-N that went up
    best_day_return: float
    worst_day_return: float
    final_equity: float          # if start = 1.0
    daily_returns: pd.Series     # indexed by date
    equity_curve: pd.Series      # indexed by date


def _fetch_next_day_ohlcv(
    stock_ids: list[int], min_date: date, max_date: date
) -> pd.DataFrame:
    """Returns OHLCV for range. Caller computes 'next day' via shift."""
    with get_session() as s:
        rows = s.execute(
            select(
                MarketDataDaily.stock_id,
                MarketDataDaily.trade_date,
                MarketDataDaily.open,
                MarketDataDaily.close,
            )
            .where(
                MarketDataDaily.stock_id.in_(stock_ids),
                MarketDataDaily.trade_date >= min_date,
                MarketDataDaily.trade_date <= max_date,
            )
            .order_by(MarketDataDaily.stock_id, MarketDataDaily.trade_date)
        ).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["stock_id", "trade_date", "open", "close"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["open"] = df["open"].astype(float)
    df["close"] = df["close"].astype(float)
    return df


def simulate_topn_strategy(
    predictions_df: pd.DataFrame,
    top_n: int = 10,
) -> SimulationResult:
    """Simulate trading.

    predictions_df columns (required):
      - trade_date  : the date on which we'd CALL the pick
      - stock_id
      - prob_up     : confidence / ranking score (higher = better)

    For each unique trade_date, we pick top N by prob_up. Then we look up
    each stock's OHLCV on `trade_date + 1 trading day` and compute the
    intraday return (open → close).
    """
    if predictions_df.empty:
        return _empty_result()

    predictions_df = predictions_df.copy()
    predictions_df["trade_date"] = pd.to_datetime(predictions_df["trade_date"])

    # All stock_ids we care about, for the date range + buffer
    all_stock_ids = predictions_df["stock_id"].unique().tolist()
    min_date = predictions_df["trade_date"].min().date()
    max_date = predictions_df["trade_date"].max().date() + pd.Timedelta(days=10)

    ohlcv = _fetch_next_day_ohlcv(all_stock_ids, min_date, pd.Timestamp(max_date).date())
    if ohlcv.empty:
        return _empty_result()

    # For each (stock_id, trade_date), find NEXT trading day's OHLCV
    ohlcv = ohlcv.sort_values(["stock_id", "trade_date"]).reset_index(drop=True)
    g = ohlcv.groupby("stock_id", group_keys=False)
    ohlcv["next_open"] = g["open"].shift(-1)
    ohlcv["next_close"] = g["close"].shift(-1)
    ohlcv["next_return"] = (ohlcv["next_close"] - ohlcv["next_open"]) / ohlcv["next_open"]

    # Merge with predictions
    keyed = predictions_df.merge(
        ohlcv[["stock_id", "trade_date", "next_return"]],
        on=["stock_id", "trade_date"],
        how="left",
    )

    daily_returns_map = {}
    hit_rate_map = {}

    for trade_date, group in keyed.groupby("trade_date"):
        top = group.nlargest(top_n, "prob_up")
        rets = top["next_return"].dropna().values
        if len(rets) == 0:
            continue
        daily_return = float(np.mean(rets))
        daily_returns_map[trade_date] = daily_return
        hit_rate_map[trade_date] = float(np.mean(rets > 0))

    if not daily_returns_map:
        return _empty_result()

    daily_series = pd.Series(daily_returns_map).sort_index()
    equity_curve = (1 + daily_series).cumprod()

    # Metrics
    n_days = len(daily_series)
    total_return = float(equity_curve.iloc[-1] - 1)
    ann_return = (1 + total_return) ** (252.0 / max(n_days, 1)) - 1 if n_days > 0 else 0

    mean_ret = daily_series.mean()
    std_ret = daily_series.std()
    sharpe = float(mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

    # Max drawdown
    roll_max = equity_curve.cummax()
    drawdown = (equity_curve / roll_max - 1).min()
    max_dd = float(drawdown)

    win_rate = float((daily_series > 0).mean())
    hit_rate_series = pd.Series(hit_rate_map).sort_index()
    overall_hit_rate = float(hit_rate_series.mean())

    return SimulationResult(
        n_days=n_days,
        total_return_pct=total_return * 100,
        annualized_return_pct=ann_return * 100,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd * 100,
        win_rate=win_rate,
        hit_rate=overall_hit_rate,
        best_day_return=float(daily_series.max()),
        worst_day_return=float(daily_series.min()),
        final_equity=float(equity_curve.iloc[-1]),
        daily_returns=daily_series,
        equity_curve=equity_curve,
    )


def _empty_result() -> SimulationResult:
    empty = pd.Series(dtype=float)
    return SimulationResult(
        n_days=0, total_return_pct=0, annualized_return_pct=0,
        sharpe_ratio=0, max_drawdown_pct=0, win_rate=0, hit_rate=0,
        best_day_return=0, worst_day_return=0, final_equity=1.0,
        daily_returns=empty, equity_curve=empty,
    )
