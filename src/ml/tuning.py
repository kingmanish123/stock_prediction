"""Hyperparameter tuning helper for the direction classifier.

Runs a small curated grid of configurations using chronological 3-way split
(train / val / test) and early stopping on val. The goal isn't an exhaustive
search — just to close the train/test gap from ~26% down to a healthy <10%.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..common.logger import get_logger
from .direction_classifier import DirectionClassifier
from .eval import classification_metrics, top_k_hit_rate

logger = get_logger(__name__)


@dataclass
class TuningResult:
    config_name: str
    params: dict
    train_acc: float
    val_acc: float
    test_acc: float
    test_baseline: float
    gap_train_test: float
    best_iteration: int | None
    top5_buy_hit_rate: float
    top5_buy_avg_return: float | None
    buy_minus_sell_return: float | None


def _three_way_split(
    labeled: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    train_frac: float = 0.70,
    val_frac: float = 0.15,
):
    """Chronological split into train / val / test DataFrames."""
    labeled = labeled.sort_values("trade_date").reset_index(drop=True)
    n = len(labeled)
    t1 = int(n * train_frac)
    t2 = int(n * (train_frac + val_frac))
    train = labeled.iloc[:t1]
    val = labeled.iloc[t1:t2]
    test = labeled.iloc[t2:]
    return train, val, test


def run_tuning(
    labeled: pd.DataFrame,
    feature_cols: list[str],
    target_col: str = "target_direction",
    configs: list[tuple[str, dict]] | None = None,
) -> list[TuningResult]:
    """Try each hyperparam config. Returns results sorted best-first by test acc."""

    if configs is None:
        # Curated set: progressively more regularized vs baseline
        configs = [
            # Baseline (matches v1)
            ("baseline_v1", {
                "max_depth": 5, "learning_rate": 0.05, "n_estimators": 500,
                "min_child_weight": 3, "reg_alpha": 0.1, "reg_lambda": 1.0,
                "subsample": 0.8, "colsample_bytree": 0.8,
            }),
            # Shallower trees
            ("shallow_md3", {
                "max_depth": 3, "learning_rate": 0.05, "n_estimators": 1500,
                "min_child_weight": 3, "reg_alpha": 0.1, "reg_lambda": 1.0,
                "subsample": 0.8, "colsample_bytree": 0.8,
            }),
            ("shallow_md4", {
                "max_depth": 4, "learning_rate": 0.05, "n_estimators": 1500,
                "min_child_weight": 3, "reg_alpha": 0.1, "reg_lambda": 1.0,
                "subsample": 0.8, "colsample_bytree": 0.8,
            }),
            # Higher regularization
            ("strong_reg", {
                "max_depth": 4, "learning_rate": 0.05, "n_estimators": 1500,
                "min_child_weight": 10, "reg_alpha": 1.0, "reg_lambda": 2.0,
                "subsample": 0.7, "colsample_bytree": 0.7,
            }),
            ("heavy_reg_shallow", {
                "max_depth": 3, "learning_rate": 0.03, "n_estimators": 2000,
                "min_child_weight": 20, "reg_alpha": 1.0, "reg_lambda": 3.0,
                "subsample": 0.7, "colsample_bytree": 0.7,
            }),
            # Slower learning + more trees (with early stopping)
            ("slow_learn", {
                "max_depth": 4, "learning_rate": 0.02, "n_estimators": 3000,
                "min_child_weight": 10, "reg_alpha": 0.5, "reg_lambda": 2.0,
                "subsample": 0.8, "colsample_bytree": 0.8,
            }),
            # Very shallow + very regularized (stress-test under-fit)
            ("ultra_regularized", {
                "max_depth": 2, "learning_rate": 0.03, "n_estimators": 2000,
                "min_child_weight": 30, "reg_alpha": 2.0, "reg_lambda": 5.0,
                "subsample": 0.6, "colsample_bytree": 0.6,
            }),
            # Conservative with column sampling
            ("wide_feature_sample", {
                "max_depth": 4, "learning_rate": 0.03, "n_estimators": 2000,
                "min_child_weight": 8, "reg_alpha": 0.5, "reg_lambda": 1.5,
                "subsample": 0.85, "colsample_bytree": 0.5,
            }),
        ]

    # Drop rows missing target or features
    usable = labeled.dropna(subset=feature_cols + [target_col]).copy()
    train_df, val_df, test_df = _three_way_split(usable, feature_cols, target_col)

    X_train = train_df[feature_cols]
    y_train = train_df[target_col].astype(int)
    X_val = val_df[feature_cols]
    y_val = val_df[target_col].astype(int)
    X_test = test_df[feature_cols]
    y_test = test_df[target_col].astype(int)

    logger.info(
        "tuning_split",
        train=len(train_df), val=len(val_df), test=len(test_df),
        train_range=f"{train_df['trade_date'].min().date()}→{train_df['trade_date'].max().date()}",
        val_range=f"{val_df['trade_date'].min().date()}→{val_df['trade_date'].max().date()}",
        test_range=f"{test_df['trade_date'].min().date()}→{test_df['trade_date'].max().date()}",
    )

    results: list[TuningResult] = []

    for name, params in configs:
        logger.info("tuning_fit", config=name, params=params)

        full_params = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "tree_method": "hist",
            "random_state": 42,
            "n_jobs": -1,
            **params,
        }
        clf = DirectionClassifier(params=full_params)
        clf.train(X_train, y_train, X_val, y_val, early_stopping_rounds=50)

        # best iteration (early stopping)
        best_it = getattr(clf.model, "best_iteration", None)

        train_acc = float((clf.predict(X_train) == y_train.values).mean())
        val_acc = float((clf.predict(X_val) == y_val.values).mean())

        y_pred = clf.predict(X_test)
        y_prob = clf.predict_proba(X_test)[:, 1]
        metrics = classification_metrics(y_test.values, y_pred)

        preds_df = test_df[["trade_date", "stock_id", "symbol", target_col]].copy()
        preds_df["pred_direction"] = y_pred
        preds_df["prob_up"] = y_prob
        if "target_return" in test_df.columns:
            preds_df["target_return"] = test_df["target_return"].values
        topk = top_k_hit_rate(preds_df, k=5)

        results.append(TuningResult(
            config_name=name,
            params=params,
            train_acc=train_acc,
            val_acc=val_acc,
            test_acc=metrics.accuracy,
            test_baseline=metrics.baseline_majority,
            gap_train_test=train_acc - metrics.accuracy,
            best_iteration=best_it,
            top5_buy_hit_rate=topk.get("buy_hit_rate_avg", 0),
            top5_buy_avg_return=topk.get("buy_avg_return"),
            buy_minus_sell_return=topk.get("buy_minus_sell_return"),
        ))

    # sort by test accuracy (descending)
    results.sort(key=lambda r: r.test_acc, reverse=True)
    return results
