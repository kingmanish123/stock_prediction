"""Walk-forward time-series cross-validation.

Classic ML cross-validation assumes iid rows — that fails for time series
(look-ahead bias leaks signal). Walk-forward is the correct approach:
  - Train on history up to time T
  - Test on T → T+window
  - Roll forward, retrain, test again

We use an EXPANDING training window (training set grows with each fold).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

import numpy as np
import pandas as pd

from ..common.logger import get_logger
from .direction_classifier import DirectionClassifier
from .eval import DirectionMetrics, classification_metrics, top_k_hit_rate

logger = get_logger(__name__)


@dataclass
class WalkForwardFold:
    fold: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    metrics: DirectionMetrics
    top_k: dict
    predictions_df: pd.DataFrame


def walk_forward_cv(
    labeled_df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str = "target_direction",
    n_folds: int = 5,
    min_train_years: float = 2.0,
    test_window_days: int = 60,
    classifier_factory: Callable[[], DirectionClassifier] = DirectionClassifier,
    verbose: bool = True,
) -> list[WalkForwardFold]:
    """Run walk-forward CV with expanding training window.

    Splits the timeline into `n_folds` test windows of `test_window_days`,
    positioned at the end of the available history. The earliest fold's test
    set starts after `min_train_years` of training data.
    """
    labeled_df = labeled_df.copy()
    labeled_df["trade_date"] = pd.to_datetime(labeled_df["trade_date"])
    labeled_df = labeled_df.sort_values("trade_date").reset_index(drop=True)

    # Drop rows with missing target or features
    usable = labeled_df.dropna(subset=[target_col] + feature_cols, how="any").copy()
    if usable.empty:
        logger.warning("walk_forward_no_data")
        return []

    min_date = usable["trade_date"].min()
    max_date = usable["trade_date"].max()

    # Compute test window placements (last N slots)
    test_end = max_date
    test_starts: list[pd.Timestamp] = []
    for _ in range(n_folds):
        test_starts.append(test_end - pd.Timedelta(days=test_window_days))
        test_end = test_end - pd.Timedelta(days=test_window_days)
    test_starts.reverse()  # earliest first

    # Validate: earliest test start must leave min_train_years of training
    earliest_train_needed = test_starts[0] - pd.Timedelta(days=int(min_train_years * 365))
    if earliest_train_needed < min_date:
        logger.warning(
            "walk_forward_shrinks_training",
            requested_min_train_years=min_train_years,
            earliest_train_needed=str(earliest_train_needed),
            data_min=str(min_date),
        )

    results: list[WalkForwardFold] = []
    for fold_idx, test_start in enumerate(test_starts, start=1):
        test_end_fold = test_start + pd.Timedelta(days=test_window_days)

        train_mask = usable["trade_date"] < test_start
        test_mask = (usable["trade_date"] >= test_start) & (usable["trade_date"] < test_end_fold)
        train = usable.loc[train_mask]
        test = usable.loc[test_mask]

        if len(train) < 500 or len(test) < 50:
            if verbose:
                logger.warning(
                    "walk_forward_fold_too_small",
                    fold=fold_idx, train_rows=len(train), test_rows=len(test),
                )
            continue

        X_train = train[feature_cols]
        y_train = train[target_col].astype(int)
        X_test = test[feature_cols]
        y_test = test[target_col].astype(int)

        clf = classifier_factory()
        clf.train(X_train, y_train)

        y_pred = clf.predict(X_test)
        y_prob = clf.predict_proba(X_test)[:, 1]

        metrics = classification_metrics(y_test.values, y_pred)

        preds_df = test[["trade_date", "stock_id", "symbol", target_col]].copy()
        preds_df["pred_direction"] = y_pred
        preds_df["prob_up"] = y_prob
        if "target_return" in test.columns:
            preds_df["target_return"] = test["target_return"].values

        topk = top_k_hit_rate(preds_df, prob_col="prob_up", actual_col=target_col, k=5)

        fold_result = WalkForwardFold(
            fold=fold_idx,
            train_start=train["trade_date"].min(),
            train_end=train["trade_date"].max(),
            test_start=test["trade_date"].min(),
            test_end=test["trade_date"].max(),
            metrics=metrics,
            top_k=topk,
            predictions_df=preds_df,
        )
        results.append(fold_result)

        if verbose:
            logger.info(
                "walk_forward_fold_done",
                fold=fold_idx,
                train=f"{train['trade_date'].min().date()}→{train['trade_date'].max().date()}",
                test=f"{test['trade_date'].min().date()}→{test['trade_date'].max().date()}",
                train_rows=len(train),
                test_rows=len(test),
                accuracy=f"{metrics.accuracy:.3f}",
                top5_buy_hit=f"{topk.get('buy_hit_rate_avg', 0):.3f}",
            )

    return results
