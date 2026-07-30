"""Train the first XGBoost direction classifier.

Flow:
  1. Build feature matrix for N years (default 4 for training) + last 1 year held out
  2. Attach next-day labels
  3. Time-based split: earlier = train, later = test
  4. Train XGBoost
  5. Evaluate: accuracy + top-5 hit rate + feature importance
  6. Save model + register in `model_versions` table

Usage:
    python scripts/train_direction_model.py                  # 4 train / 1 test
    python scripts/train_direction_model.py --years 3
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from rich.console import Console
from rich.table import Table

from src.common.config import MODELS_DIR
from src.common.logger import setup_logging
from src.db.models import ModelVersion
from src.db.session import get_session
from src.features.assembler import ALL_FEATURE_COLS, build_feature_matrix
from src.ml.direction_classifier import DirectionClassifier
from src.ml.eval import classification_metrics, top_k_hit_rate
from src.ml.labels import add_labels

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=int, default=4, help="Years of data to use (default 4)")
    p.add_argument("--test-fraction", type=float, default=0.2,
                   help="Fraction held out for test (chronological tail)")
    p.add_argument("--feature-file", type=str,
                   help="Path to pre-built features parquet (skips rebuild)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    end = date.today()
    start = end - timedelta(days=args.years * 365)

    if args.feature_file:
        console.print(f"[cyan]▶ Loading features from {args.feature_file}[/cyan]")
        features = pd.read_parquet(args.feature_file)
    else:
        console.print(f"[cyan]▶ Building features: {start} → {end}[/cyan]")
        features = build_feature_matrix(start, end, write_parquet=True)
    console.print(f"  Raw feature rows: {len(features):,}")

    console.print(f"\n[cyan]▶ Attaching next-day labels[/cyan]")
    labeled = add_labels(features)

    usable = labeled.dropna(subset=ALL_FEATURE_COLS + ["target_direction"], how="any")
    console.print(f"  Rows with full features + labels: {len(usable):,}")
    console.print(f"  Dropped (incomplete/no next-day): {len(labeled) - len(usable):,}")

    # Chronological split
    usable = usable.sort_values("trade_date").reset_index(drop=True)
    split_idx = int(len(usable) * (1 - args.test_fraction))
    train = usable.iloc[:split_idx]
    test = usable.iloc[split_idx:]

    split_date = train["trade_date"].iloc[-1]
    console.print(
        f"\n[cyan]▶ Time-based split at [bold]{split_date.date()}[/bold]:[/cyan]"
    )
    console.print(f"  Train: {len(train):,} rows  [{train['trade_date'].min().date()} → {train['trade_date'].max().date()}]")
    console.print(f"  Test : {len(test):,} rows   [{test['trade_date'].min().date()} → {test['trade_date'].max().date()}]")

    X_train = train[ALL_FEATURE_COLS]
    y_train = train["target_direction"].astype(int)
    X_test = test[ALL_FEATURE_COLS]
    y_test = test["target_direction"].astype(int)

    # Class balance
    balance_train = y_train.mean()
    balance_test = y_test.mean()
    console.print(f"  Train UP rate: {balance_train:.3f}  |  Test UP rate: {balance_test:.3f}")

    # ─── train ────────────────────────────────────────────────────
    console.print(f"\n[cyan]▶ Training XGBoost direction classifier[/cyan]")
    clf = DirectionClassifier()
    train_metrics = clf.train(X_train, y_train)
    console.print(f"  Train accuracy: {train_metrics['train_accuracy']:.3f}")

    # ─── evaluate ─────────────────────────────────────────────────
    y_pred = clf.predict(X_test)
    y_prob = clf.predict_proba(X_test)[:, 1]

    metrics = classification_metrics(y_test.values, y_pred)
    console.print(f"\n[cyan]▶ Test metrics[/cyan]")
    mt = Table(show_header=False)
    mt.add_column("", style="cyan")
    mt.add_column("", style="green")
    mt.add_row("Accuracy", f"{metrics.accuracy:.3f}")
    mt.add_row("Baseline (majority class)", f"{metrics.baseline_majority:.3f}")
    mt.add_row("Edge over baseline", f"{metrics.accuracy - metrics.baseline_majority:+.3f}")
    mt.add_row("Precision (UP)", f"{metrics.precision_up:.3f}")
    mt.add_row("Recall (UP)", f"{metrics.recall_up:.3f}")
    mt.add_row("Precision (DOWN)", f"{metrics.precision_down:.3f}")
    mt.add_row("Recall (DOWN)", f"{metrics.recall_down:.3f}")
    mt.add_row("Confusion TN/FP/FN/TP",
               f"{metrics.true_negative}/{metrics.false_positive}/{metrics.false_negative}/{metrics.true_positive}")
    mt.add_row("Test row count", str(metrics.count))
    console.print(mt)

    # Top-5 hit rate (the user's primary validation metric)
    preds_df = test[["trade_date", "stock_id", "symbol", "target_direction", "target_return"]].copy()
    preds_df["pred_direction"] = y_pred
    preds_df["prob_up"] = y_prob
    topk = top_k_hit_rate(preds_df, k=5)

    console.print(f"\n[cyan]▶ Top-5 daily ranking metrics (user's primary target: ≥ 3/5)[/cyan]")
    tt = Table(show_header=False)
    tt.add_column("", style="cyan")
    tt.add_column("", style="green")
    tt.add_row("Dates evaluated", str(topk.get("n_dates", 0)))
    tt.add_row("Avg Top-5 BUY hits", f"{topk.get('avg_buy_hits_of_5', 0):.2f} / 5")
    tt.add_row("Top-5 BUY hit rate", f"{topk.get('buy_hit_rate_avg', 0):.3f}")
    tt.add_row("Top-5 SELL hit rate", f"{topk.get('sell_hit_rate_avg', 0):.3f}")
    tt.add_row("Dates with ≥3/5 BUY wins", str(topk.get("dates_3_or_more_buys", 0)))
    if "buy_avg_return" in topk:
        tt.add_row("Avg return of Top-5 BUY picks", f"{topk['buy_avg_return']:+.4%}")
        tt.add_row("Avg return of Top-5 SELL picks", f"{topk['sell_avg_return']:+.4%}")
        tt.add_row("BUY − SELL return spread", f"{topk['buy_minus_sell_return']:+.4%}")
    console.print(tt)

    # Feature importance (top 20)
    console.print(f"\n[cyan]▶ Top-20 features by gain[/cyan]")
    importance = clf.feature_importance(importance_type="gain")
    total_gain = importance.sum()
    fi_table = Table()
    fi_table.add_column("#", style="dim")
    fi_table.add_column("Feature", style="cyan")
    fi_table.add_column("Gain %", style="green", justify="right")
    for i, (feat, gain) in enumerate(importance.head(20).items(), 1):
        pct = 100 * gain / total_gain if total_gain else 0
        fi_table.add_row(str(i), feat, f"{pct:.2f}%")
    console.print(fi_table)

    # ─── persist model + register in DB ───────────────────────────
    version = f"v1_direction_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    model_path = MODELS_DIR / f"{version}.pkl"
    clf.save(model_path)
    console.print(f"\n[green]✓ Model saved: {model_path}[/green]")

    metrics_payload = {
        "classification": metrics.as_dict(),
        "top_k": topk,
        "train_metrics": train_metrics,
    }
    with get_session() as s:
        mv = ModelVersion(
            model_name="direction_classifier",
            version=version,
            algorithm="xgboost",
            trained_at=datetime.utcnow(),
            training_data_from=train["trade_date"].min().date(),
            training_data_to=train["trade_date"].max().date(),
            num_training_samples=len(train),
            features_used=ALL_FEATURE_COLS,
            hyperparameters=clf.params,
            validation_accuracy=float(metrics.accuracy),
            validation_precision=float(metrics.precision_up),
            validation_recall=float(metrics.recall_up),
            validation_f1=float(metrics.f1_up),
            validation_metrics=metrics_payload,
            feature_importance=dict(importance.items()),
            is_active=True,
            deployed_at=datetime.utcnow(),
            file_path=str(model_path),
            notes=f"Trained on {len(train):,} rows, tested on {len(test):,}",
        )
        # Deactivate previous models of same name
        from sqlalchemy import update as sqla_update
        s.execute(
            sqla_update(ModelVersion)
            .where(ModelVersion.model_name == "direction_classifier")
            .values(is_active=False)
        )
        s.add(mv)

    console.print(f"[green]✓ Registered in model_versions table: {version}[/green]")
    console.print(f"\n[bold green]✓ Training complete[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
