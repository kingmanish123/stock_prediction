"""Calendar-based features — day of week, F&O expiry, earnings proximity."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from ..db.models import CorporateEvent, EventStatus, EventType
from ..db.session import get_session


def _is_last_thursday_of_month(d: date) -> bool:
    """F&O monthly contracts expire on the last Thursday of the month in India."""
    if d.weekday() != 3:  # 3 = Thursday
        return False
    # Check if next Thursday is in same month
    next_thu = d + timedelta(days=7)
    return next_thu.month != d.month


def _is_thursday_of_week(d: date) -> bool:
    """Weekly F&O (Nifty, Bank Nifty) expire on Thursday."""
    return d.weekday() == 3


def add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adds purely date-driven features.

    Expects DataFrame with a date-typed index (or a 'trade_date' column).
    """
    out = df.copy()
    idx = out.index
    # Handle both DatetimeIndex and plain DataFrame with trade_date
    if not isinstance(idx, pd.DatetimeIndex):
        if "trade_date" in out.columns:
            idx = pd.to_datetime(out["trade_date"])
        else:
            idx = pd.to_datetime(idx)

    day_of_week = idx.dayofweek  # Mon=0 ... Sun=6
    out["day_of_week"] = day_of_week
    out["is_monday"] = (day_of_week == 0).astype(int)
    out["is_friday"] = (day_of_week == 4).astype(int)

    # Expiry flags (Indian F&O)
    dates_only = [d.date() if hasattr(d, "date") else d for d in idx]
    out["is_weekly_expiry"] = [int(_is_thursday_of_week(d)) for d in dates_only]
    out["is_monthly_expiry"] = [int(_is_last_thursday_of_month(d)) for d in dates_only]

    out["day_of_month"] = idx.day
    out["month"] = idx.month
    out["quarter"] = idx.quarter

    return out


def load_earnings_proximity(
    stock_ids: list[int], start: date, end: date
) -> pd.DataFrame:
    """For each (stock_id, trade_date), compute days until next earnings event.

    Returns long-format DataFrame with columns: stock_id, trade_date,
    days_to_earnings, is_earnings_day.
    """
    # Pull all earnings events for our stock universe within and after our window
    with get_session() as s:
        rows = s.execute(
            select(
                CorporateEvent.stock_id,
                CorporateEvent.event_date,
                CorporateEvent.event_type,
            ).where(
                CorporateEvent.stock_id.in_(stock_ids),
                CorporateEvent.event_type == EventType.EARNINGS_ANNOUNCEMENT.value,
                CorporateEvent.event_date >= start,
                CorporateEvent.event_date <= end + timedelta(days=180),
            )
        ).all()

    if not rows:
        # No earnings data — return empty frame with correct columns
        return pd.DataFrame(columns=["stock_id", "trade_date", "days_to_earnings", "is_earnings_day"])

    earnings_df = pd.DataFrame(rows, columns=["stock_id", "event_date", "event_type"])
    earnings_df["event_date"] = pd.to_datetime(earnings_df["event_date"])

    # Build date × stock grid
    all_dates = pd.date_range(start=start, end=end, freq="B")  # business days
    grid = pd.MultiIndex.from_product(
        [stock_ids, all_dates], names=["stock_id", "trade_date"]
    ).to_frame(index=False)

    # For each row, find closest future earnings
    # Efficient approach: for each stock, sort earnings, then for each trade_date find next
    result_rows = []
    for stock_id in stock_ids:
        stock_earnings = (
            earnings_df[earnings_df["stock_id"] == stock_id]["event_date"]
            .sort_values()
            .reset_index(drop=True)
        )
        if stock_earnings.empty:
            # No earnings data for this stock — assign high sentinel value
            for trade_date in all_dates:
                result_rows.append((stock_id, trade_date.date(), 999, 0))
            continue
        for trade_date in all_dates:
            next_earnings = stock_earnings[stock_earnings >= trade_date]
            if next_earnings.empty:
                days_to = 999
                is_earnings = 0
            else:
                days_to = (next_earnings.iloc[0] - trade_date).days
                is_earnings = 1 if days_to == 0 else 0
            result_rows.append((stock_id, trade_date.date(), days_to, is_earnings))

    return pd.DataFrame(
        result_rows,
        columns=["stock_id", "trade_date", "days_to_earnings", "is_earnings_day"],
    )


TEMPORAL_FEATURE_COLS: list[str] = [
    "day_of_week",
    "is_monday",
    "is_friday",
    "is_weekly_expiry",
    "is_monthly_expiry",
    "day_of_month",
    "month",
    "quarter",
]

EARNINGS_FEATURE_COLS: list[str] = [
    "days_to_earnings",
    "is_earnings_day",
]
