"""Evaluation metrics for direction classification + top-K stock ranking."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DirectionMetrics:
    accuracy: float
    precision_up: float
    recall_up: float
    precision_down: float
    recall_down: float
    f1_up: float
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int
    baseline_majority: float  # accuracy if always predict majority class
    count: int

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> DirectionMetrics:
    """Binary classification metrics (0=DOWN, 1=UP)."""
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)

    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    total = tp + tn + fp + fn

    accuracy = (tp + tn) / total if total else 0.0
    prec_up = tp / (tp + fp) if (tp + fp) else 0.0
    rec_up = tp / (tp + fn) if (tp + fn) else 0.0
    prec_dn = tn / (tn + fn) if (tn + fn) else 0.0
    rec_dn = tn / (tn + fp) if (tn + fp) else 0.0
    f1_up = 2 * prec_up * rec_up / (prec_up + rec_up) if (prec_up + rec_up) else 0.0

    base_majority = max((y_true == 1).mean(), (y_true == 0).mean())

    return DirectionMetrics(
        accuracy=accuracy,
        precision_up=prec_up,
        recall_up=rec_up,
        precision_down=prec_dn,
        recall_down=rec_dn,
        f1_up=f1_up,
        true_positive=tp,
        true_negative=tn,
        false_positive=fp,
        false_negative=fn,
        baseline_majority=base_majority,
        count=total,
    )


def top_k_hit_rate(
    df: pd.DataFrame,
    date_col: str = "trade_date",
    prob_col: str = "prob_up",
    actual_col: str = "target_direction",
    k: int = 5,
) -> dict:
    """For each date, select top-K most-confident UP predictions, measure hit rate.

    Also measures top-K SELL hit rate (least-confident UP = most confident DOWN).

    Returns: {
        'buy_hit_rate_avg': avg of hits/k across dates,
        'sell_hit_rate_avg': ...,
        'buy_avg_return': avg return of top-K BUY picks if return col present,
        'sell_avg_return': ...,
        'n_dates': number of dates evaluated,
    }
    """
    results = []
    has_return = "target_return" in df.columns

    for trade_date, group in df.groupby(date_col):
        if len(group) < k * 2:
            continue

        # Top-K most confident UP
        top_buy = group.nlargest(k, prob_col)
        # Top-K least confident UP (i.e., strongest DOWN)
        top_sell = group.nsmallest(k, prob_col)

        buy_hits = int((top_buy[actual_col] == 1).sum())
        sell_hits = int((top_sell[actual_col] == 0).sum())

        row = {
            "trade_date": trade_date,
            "buy_hits": buy_hits,
            "sell_hits": sell_hits,
            "buy_hit_rate": buy_hits / k,
            "sell_hit_rate": sell_hits / k,
        }
        if has_return:
            row["buy_avg_return"] = float(top_buy["target_return"].mean())
            row["sell_avg_return"] = float(top_sell["target_return"].mean())
        results.append(row)

    if not results:
        return {"n_dates": 0}

    res_df = pd.DataFrame(results)
    out = {
        "n_dates": len(res_df),
        "buy_hit_rate_avg": float(res_df["buy_hit_rate"].mean()),
        "sell_hit_rate_avg": float(res_df["sell_hit_rate"].mean()),
        "avg_buy_hits_of_5": float(res_df["buy_hits"].mean()),
        "avg_sell_hits_of_5": float(res_df["sell_hits"].mean()),
        "dates_3_or_more_buys": int((res_df["buy_hits"] >= 3).sum()),
    }
    if has_return:
        out["buy_avg_return"] = float(res_df["buy_avg_return"].mean())
        out["sell_avg_return"] = float(res_df["sell_avg_return"].mean())
        out["buy_minus_sell_return"] = out["buy_avg_return"] - out["sell_avg_return"]
    return out
