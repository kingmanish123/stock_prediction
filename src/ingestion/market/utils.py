"""Shared utility functions for market data ingestion modules."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd


def safe_decimal(v, places: int = 4) -> Decimal | None:
    """Convert any numeric-like value to Decimal, or None if NaN/invalid."""
    if v is None or pd.isna(v):
        return None
    try:
        q = Decimal("1." + "0" * places) if places > 0 else Decimal("1")
        return Decimal(str(v)).quantize(q)
    except (InvalidOperation, ValueError):
        return None


def safe_int(v) -> int | None:
    if v is None or pd.isna(v):
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None
