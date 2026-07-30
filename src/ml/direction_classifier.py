"""XGBoost direction classifier wrapper.

Binary classifier: 1 = next-day UP, 0 = next-day DOWN.
Usage:
    clf = DirectionClassifier()
    clf.train(X_train, y_train, X_val, y_val)
    probs = clf.predict_proba(X_test)
    dirs  = clf.predict(X_test)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier


@dataclass
class DirectionClassifier:
    params: dict = field(
        default_factory=lambda: {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "max_depth": 5,
            "learning_rate": 0.05,
            "n_estimators": 500,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 3,
            "gamma": 0.1,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "tree_method": "hist",
            "random_state": 42,
            "n_jobs": -1,
        }
    )
    model: XGBClassifier | None = None
    feature_names: list[str] = field(default_factory=list)

    # ─── training ─────────────────────────────────────────────────
    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series | np.ndarray,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | np.ndarray | None = None,
        early_stopping_rounds: int | None = 50,
    ) -> dict:
        self.feature_names = list(X_train.columns)
        params = dict(self.params)
        if early_stopping_rounds and X_val is not None:
            params["early_stopping_rounds"] = early_stopping_rounds
        self.model = XGBClassifier(**params)

        eval_set = [(X_val, y_val)] if X_val is not None and y_val is not None else None
        self.model.fit(X_train, y_train, eval_set=eval_set, verbose=False)

        # training metrics
        train_pred = self.model.predict(X_train)
        train_acc = float((train_pred == np.asarray(y_train)).mean())
        metrics = {"train_accuracy": train_acc, "n_features": len(self.feature_names)}
        if X_val is not None and y_val is not None:
            val_pred = self.model.predict(X_val)
            val_acc = float((val_pred == np.asarray(y_val)).mean())
            metrics["val_accuracy"] = val_acc
        return metrics

    # ─── inference ────────────────────────────────────────────────
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("model not trained")
        X = self._ensure_feature_order(X)
        return self.model.predict(X)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("model not trained")
        X = self._ensure_feature_order(X)
        return self.model.predict_proba(X)

    def _ensure_feature_order(self, X: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in self.feature_names if c not in X.columns]
        if missing:
            raise ValueError(f"Missing features at inference: {missing[:5]}...")
        return X[self.feature_names]

    # ─── introspection ────────────────────────────────────────────
    def feature_importance(self, importance_type: str = "gain") -> pd.Series:
        if self.model is None:
            raise RuntimeError("model not trained")
        booster = self.model.get_booster()
        raw = booster.get_score(importance_type=importance_type)
        # XGBoost returns features as 'f0', 'f1', ... — remap to names
        if raw and list(raw.keys())[0].startswith("f"):
            name_map = {f"f{i}": name for i, name in enumerate(self.feature_names)}
            raw = {name_map.get(k, k): v for k, v in raw.items()}
        s = pd.Series(raw, name=importance_type).sort_values(ascending=False)
        # Ensure all features are represented (0 if not used)
        s = s.reindex(self.feature_names, fill_value=0.0)
        return s.sort_values(ascending=False)

    # ─── persistence ──────────────────────────────────────────────
    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self.model, "feature_names": self.feature_names, "params": self.params},
            path,
        )

    @classmethod
    def load(cls, path: str | Path) -> "DirectionClassifier":
        data = joblib.load(path)
        clf = cls()
        clf.model = data["model"]
        clf.feature_names = data["feature_names"]
        clf.params = data.get("params", clf.params)
        return clf
