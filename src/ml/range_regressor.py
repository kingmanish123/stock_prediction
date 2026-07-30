"""XGBoost regressor for intraday range (predicted high / low as % of open).

Two regressors:
  • high_pct_regressor → predicts (next_high - next_open) / next_open  (always ≥ 0)
  • low_pct_regressor  → predicts (next_low  - next_open) / next_open  (always ≤ 0)

Combined with a reference price (today's close ≈ tomorrow's open), these give
predicted absolute price targets: entry, upside target, downside stop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor


VALID_TARGETS = {"high_pct", "low_pct"}


@dataclass
class RangeRegressor:
    target_type: str = "high_pct"
    params: dict = field(
        default_factory=lambda: {
            "objective": "reg:squarederror",
            "eval_metric": "mae",
            "max_depth": 4,
            "learning_rate": 0.05,
            "n_estimators": 800,
            "min_child_weight": 5,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "tree_method": "hist",
            "random_state": 42,
            "n_jobs": -1,
        }
    )
    model: XGBRegressor | None = None
    feature_names: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.target_type not in VALID_TARGETS:
            raise ValueError(f"target_type must be one of {VALID_TARGETS}")

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
        self.model = XGBRegressor(**params)

        eval_set = [(X_val, y_val)] if X_val is not None and y_val is not None else None
        self.model.fit(X_train, y_train, eval_set=eval_set, verbose=False)

        train_pred = self.model.predict(X_train)
        train_mae = float(np.mean(np.abs(train_pred - np.asarray(y_train))))
        # Mean absolute percentage error of the prediction magnitude itself
        nonzero_mask = np.asarray(y_train) != 0
        train_mape = None
        if nonzero_mask.any():
            train_mape = float(
                np.mean(
                    np.abs(
                        (train_pred[nonzero_mask] - np.asarray(y_train)[nonzero_mask])
                        / np.asarray(y_train)[nonzero_mask]
                    )
                )
            )

        metrics = {
            "train_mae": train_mae,
            "train_mape": train_mape,
            "n_features": len(self.feature_names),
        }
        if X_val is not None and y_val is not None:
            val_pred = self.model.predict(X_val)
            val_mae = float(np.mean(np.abs(val_pred - np.asarray(y_val))))
            metrics["val_mae"] = val_mae
            metrics["best_iteration"] = getattr(self.model, "best_iteration", None)
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model not trained")
        missing = [c for c in self.feature_names if c not in X.columns]
        if missing:
            raise ValueError(f"Missing features at inference: {missing[:3]}")
        return self.model.predict(X[self.feature_names])

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "feature_names": self.feature_names,
                "target_type": self.target_type,
                "params": self.params,
            },
            path,
        )

    @classmethod
    def load(cls, path: str | Path) -> "RangeRegressor":
        data = joblib.load(path)
        obj = cls(target_type=data["target_type"])
        obj.model = data["model"]
        obj.feature_names = data["feature_names"]
        obj.params = data.get("params", obj.params)
        return obj

    def feature_importance(self) -> pd.Series:
        if self.model is None:
            raise RuntimeError("Model not trained")
        booster = self.model.get_booster()
        raw = booster.get_score(importance_type="gain")
        if raw and list(raw.keys())[0].startswith("f"):
            name_map = {f"f{i}": name for i, name in enumerate(self.feature_names)}
            raw = {name_map.get(k, k): v for k, v in raw.items()}
        s = pd.Series(raw, name="gain").sort_values(ascending=False)
        return s.reindex(self.feature_names, fill_value=0.0).sort_values(ascending=False)
