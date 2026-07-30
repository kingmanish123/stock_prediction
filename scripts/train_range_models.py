"""Train range regressors (high_pct and low_pct) for intraday price band prediction.

Both models use the same feature matrix + 3-way chronological split as our
direction classifier. They're smaller targets than direction — MAE ~0.5-1%
on a typical Nifty 100 stock is a reasonable outcome.

Usage:
    python scripts/train_range_models.py --feature-file data/features/features_2021-04-23_2026-04-22.parquet
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from rich.console import Console
from rich.table import Table
from sqlalchemy import update

from src.common.config import MODELS_DIR
from src.common.logger import setup_logging
from src.db.models import ModelVersion
from src.db.session import get_session
from src.features.assembler import ALL_FEATURE_COLS, build_feature_matrix
from src.ml.labels import add_labels
from src.ml.range_regressor import RangeRegressor
from src.ml.tuning import _three_way_split

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--feature-file", type=str)
    return p.parse_args()


def _train_one(
    target_col: str,
    target_type: str,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
) -> tuple[RangeRegressor, dict]:
    X_tr = train_df[ALL_FEATURE_COLS]
    y_tr = train_df[target_col].astype(float)
    X_v = val_df[ALL_FEATURE_COLS]
    y_v = val_df[target_col].astype(float)
    X_te = test_df[ALL_FEATURE_COLS]
    y_te = test_df[target_col].astype(float)

    clf = RangeRegressor(target_type=target_type)
    metrics = clf.train(X_tr, y_tr, X_v, y_v, early_stopping_rounds=50)

    # Test set metrics
    import numpy as np
    test_pred = clf.predict(X_te)
    test_mae = float(np.mean(np.abs(test_pred - y_te.values)))
    # How often does predicted sign match actual sign
    sign_match = float(np.mean(np.sign(test_pred) == np.sign(y_te.values)))
    # Correlation
    corr = float(np.corrcoef(test_pred, y_te.values)[0, 1]) if len(test_pred) > 1 else 0.0

    metrics.update({
        "test_mae": test_mae,
        "test_sign_match": sign_match,
        "test_correlation": corr,
    })
    return clf, metrics


def _register_model(
    clf: RangeRegressor,
    model_name: str,
    version: str,
    train_df: pd.DataFrame,
    metrics: dict,
    file_path: Path,
) -> None:
    with get_session() as s:
        s.execute(
            update(ModelVersion)
            .where(ModelVersion.model_name == model_name)
            .values(is_active=False)
        )
        mv = ModelVersion(
            model_name=model_name,
            version=version,
            algorithm="xgboost_regression",
            trained_at=datetime.utcnow(),
            training_data_from=train_df["trade_date"].min().date(),
            training_data_to=train_df["trade_date"].max().date(),
            num_training_samples=len(train_df),
            features_used=ALL_FEATURE_COLS,
            hyperparameters=clf.params,
            validation_metrics=metrics,
            is_active=True,
            deployed_at=datetime.utcnow(),
            file_path=str(file_path),
            notes=f"Range regressor: {clf.target_type}",
        )
        s.add(mv)


def main() -> int:
    args = parse_args()
    end = date.today()
    start = end - timedelta(days=args.years * 365)

    if args.feature_file:
        features = pd.read_parquet(args.feature_file)
    else:
        features = build_feature_matrix(start, end, write_parquet=True)
    console.print(f"[cyan]▶ Features: {len(features):,} rows[/cyan]")

    labeled = add_labels(features)
    labeled["trade_date"] = pd.to_datetime(labeled["trade_date"])
    labeled = labeled.dropna(
        subset=ALL_FEATURE_COLS + ["target_high_pct", "target_low_pct"]
    ).copy()
    console.print(f"  Usable rows after labels+feature completeness: {len(labeled):,}")

    train_df, val_df, test_df = _three_way_split(labeled, ALL_FEATURE_COLS, "target_high_pct")
    console.print(
        f"  Split — train {len(train_df):,}  val {len(val_df):,}  test {len(test_df):,}"
    )

    results_table = Table(title="Range regressors")
    results_table.add_column("Target", style="cyan bold")
    results_table.add_column("Train MAE", justify="right")
    results_table.add_column("Val MAE", justify="right")
    results_table.add_column("Test MAE", justify="right", style="green")
    results_table.add_column("Sign match", justify="right")
    results_table.add_column("Correlation", justify="right", style="yellow")
    results_table.add_column("Best iter", justify="right", style="dim")

    # Train high_pct model
    console.print(f"\n[cyan]▶ Training high_pct regressor[/cyan]")
    high_clf, high_metrics = _train_one(
        target_col="target_high_pct",
        target_type="high_pct",
        train_df=train_df, val_df=val_df, test_df=test_df,
    )
    high_version = f"v1_range_high_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    high_path = MODELS_DIR / f"{high_version}.pkl"
    high_clf.save(high_path)
    _register_model(high_clf, "range_high_regressor", high_version, train_df, high_metrics, high_path)

    results_table.add_row(
        "high_pct",
        f"{high_metrics['train_mae']*100:.3f}%",
        f"{high_metrics['val_mae']*100:.3f}%",
        f"{high_metrics['test_mae']*100:.3f}%",
        f"{high_metrics['test_sign_match']:.3f}",
        f"{high_metrics['test_correlation']:.3f}",
        str(high_metrics.get("best_iteration", "—")),
    )
    console.print(f"  [green]✓ Saved + registered: {high_version}[/green]")

    # Train low_pct model
    console.print(f"\n[cyan]▶ Training low_pct regressor[/cyan]")
    low_clf, low_metrics = _train_one(
        target_col="target_low_pct",
        target_type="low_pct",
        train_df=train_df, val_df=val_df, test_df=test_df,
    )
    low_version = f"v1_range_low_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    low_path = MODELS_DIR / f"{low_version}.pkl"
    low_clf.save(low_path)
    _register_model(low_clf, "range_low_regressor", low_version, train_df, low_metrics, low_path)

    results_table.add_row(
        "low_pct",
        f"{low_metrics['train_mae']*100:.3f}%",
        f"{low_metrics['val_mae']*100:.3f}%",
        f"{low_metrics['test_mae']*100:.3f}%",
        f"{low_metrics['test_sign_match']:.3f}",
        f"{low_metrics['test_correlation']:.3f}",
        str(low_metrics.get("best_iteration", "—")),
    )
    console.print(f"  [green]✓ Saved + registered: {low_version}[/green]")

    console.print()
    console.print(results_table)

    # Top features for high regressor
    console.print(f"\n[cyan]▶ Top-10 features (high_pct gain)[/cyan]")
    importance = high_clf.feature_importance()
    ft = Table()
    ft.add_column("#", style="dim")
    ft.add_column("Feature", style="cyan")
    ft.add_column("Gain", justify="right", style="green")
    total = importance.sum() or 1
    for i, (feat, gain) in enumerate(importance.head(10).items(), 1):
        ft.add_row(str(i), feat, f"{100 * gain / total:.1f}%")
    console.print(ft)

    return 0


if __name__ == "__main__":
    sys.exit(main())
