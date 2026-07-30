"""Comprehensive backtest — simulates daily top-10 XGBoost strategy with P&L.

Uses walk-forward cross-validation to train/test fairly (no look-ahead):
  - For each fold: train on past, predict test window, simulate trading
  - Aggregate predictions across all folds
  - Compute: total return, Sharpe, MaxDD, win rate, hit rate

Also compares vs:
  - Buy-and-hold Nifty 50 (^NSEI)
  - Random 10-stock picks

Usage:
    python scripts/comprehensive_backtest.py --years 5 --folds 6 --top-n 10
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import select

from src.common.logger import setup_logging
from src.db.models import GlobalIndexDaily
from src.db.session import get_session
from src.features.assembler import ALL_FEATURE_COLS, build_feature_matrix
from src.ml.labels import add_labels
from src.ml.pnl_simulator import simulate_topn_strategy
from src.ml.walk_forward import walk_forward_cv

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--folds", type=int, default=6)
    p.add_argument("--test-days", type=int, default=60)
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--feature-file", type=str)
    return p.parse_args()


def _benchmark_nifty_returns(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Daily ^NSEI returns (intraday open→close) over backtest window."""
    with get_session() as s:
        rows = s.execute(
            select(
                GlobalIndexDaily.trade_date,
                GlobalIndexDaily.open,
                GlobalIndexDaily.close,
            )
            .where(
                GlobalIndexDaily.index_symbol == "^NSEI",
                GlobalIndexDaily.trade_date >= start.date(),
                GlobalIndexDaily.trade_date <= end.date(),
            )
            .order_by(GlobalIndexDaily.trade_date)
        ).all()
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["date", "open", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df["open"] = df["open"].astype(float)
    df["close"] = df["close"].astype(float)
    df["ret"] = (df["close"] - df["open"]) / df["open"]
    return df.set_index("date")["ret"]


def _random_benchmark(predictions_df: pd.DataFrame, top_n: int, seed: int = 42) -> pd.DataFrame:
    """Produce predictions_df-shaped frame with random prob_up for baseline."""
    rng = np.random.default_rng(seed)
    out = predictions_df.copy()
    out["prob_up"] = rng.random(len(out))
    return out


def _format_pct(x: float, decimals: int = 2) -> str:
    return f"{x:+.{decimals}f}%"


def _result_row(name: str, result) -> list:
    return [
        name,
        str(result.n_days),
        f"{result.final_equity:.4f}",
        _format_pct(result.total_return_pct),
        _format_pct(result.annualized_return_pct),
        f"{result.sharpe_ratio:.3f}",
        _format_pct(result.max_drawdown_pct),
        f"{result.win_rate:.3f}",
        f"{result.hit_rate:.3f}",
    ]


def main() -> int:
    args = parse_args()
    end = date.today()
    start = end - timedelta(days=args.years * 365)

    console.print(
        Panel.fit(
            f"[bold]Comprehensive Backtest[/bold]\n"
            f"Period: {start} → {end}\n"
            f"Folds: {args.folds} × {args.test_days}d test windows\n"
            f"Strategy: Top-{args.top_n} XGBoost, daily rebalance",
            border_style="cyan",
        )
    )

    if args.feature_file:
        features = pd.read_parquet(args.feature_file)
    else:
        features = build_feature_matrix(start, end, write_parquet=True)

    labeled = add_labels(features)
    labeled["trade_date"] = pd.to_datetime(labeled["trade_date"])

    # 1. Run walk-forward CV ─────────────────────────────────────────
    console.print("\n[cyan]▶ Running walk-forward cross-validation[/cyan]")
    folds = walk_forward_cv(
        labeled,
        feature_cols=ALL_FEATURE_COLS,
        n_folds=args.folds,
        test_window_days=args.test_days,
        min_train_years=2.0,
        verbose=False,
    )
    console.print(f"  [green]✓[/green] {len(folds)} folds completed")

    # 2. Aggregate predictions across folds ─────────────────────────
    all_preds = pd.concat([f.predictions_df for f in folds], ignore_index=True)
    console.print(f"  Total prediction rows across all folds: {len(all_preds):,}")

    # 3. Simulate P&L ─────────────────────────────────────────────────
    console.print(f"\n[cyan]▶ Simulating top-{args.top_n} strategy P&L[/cyan]")
    xgb_result = simulate_topn_strategy(all_preds, top_n=args.top_n)

    # 4. Random benchmark ─────────────────────────────────────────────
    console.print(f"[cyan]▶ Random baseline (same test dates)[/cyan]")
    rand_preds = _random_benchmark(all_preds, top_n=args.top_n)
    random_result = simulate_topn_strategy(rand_preds, top_n=args.top_n)

    # 5. Nifty buy-and-hold benchmark ─────────────────────────────────
    start_ts = all_preds["trade_date"].min()
    end_ts = all_preds["trade_date"].max() + pd.Timedelta(days=5)
    bench = _benchmark_nifty_returns(start_ts, end_ts)
    # Restrict to dates our strategy had picks for
    strategy_dates = xgb_result.daily_returns.index
    bench_aligned = bench.reindex(strategy_dates).dropna()

    # Build a pseudo SimulationResult for Nifty (same metrics framework)
    from src.ml.pnl_simulator import SimulationResult
    if not bench_aligned.empty:
        equity = (1 + bench_aligned).cumprod()
        total = float(equity.iloc[-1] - 1)
        ann = (1 + total) ** (252 / len(bench_aligned)) - 1
        mean_r = bench_aligned.mean()
        std_r = bench_aligned.std()
        sharpe = float(mean_r / std_r * np.sqrt(252)) if std_r > 0 else 0
        roll_max = equity.cummax()
        dd = float((equity / roll_max - 1).min())
        nifty_result = SimulationResult(
            n_days=len(bench_aligned),
            total_return_pct=total * 100,
            annualized_return_pct=ann * 100,
            sharpe_ratio=sharpe,
            max_drawdown_pct=dd * 100,
            win_rate=float((bench_aligned > 0).mean()),
            hit_rate=float((bench_aligned > 0).mean()),
            best_day_return=float(bench_aligned.max()),
            worst_day_return=float(bench_aligned.min()),
            final_equity=float(equity.iloc[-1]),
            daily_returns=bench_aligned,
            equity_curve=equity,
        )
    else:
        nifty_result = None

    # 6. Results table ────────────────────────────────────────────────
    tbl = Table(title="Simulated strategy P&L (intraday open→close)")
    tbl.add_column("Strategy", style="cyan bold")
    tbl.add_column("Days", justify="right")
    tbl.add_column("Equity (₹1 start)", justify="right")
    tbl.add_column("Total return", justify="right", style="green")
    tbl.add_column("Ann. return", justify="right", style="green")
    tbl.add_column("Sharpe", justify="right", style="yellow")
    tbl.add_column("Max DD", justify="right", style="red")
    tbl.add_column("Win rate", justify="right")
    tbl.add_column("Hit rate", justify="right")

    tbl.add_row(*_result_row("XGBoost Top-10", xgb_result))
    tbl.add_row(*_result_row("Random Top-10", random_result))
    if nifty_result:
        tbl.add_row(*_result_row("Nifty 50 (buy-hold intraday)", nifty_result))
    console.print(tbl)

    # 7. Verdict ──────────────────────────────────────────────────────
    spread_vs_random = xgb_result.total_return_pct - random_result.total_return_pct
    spread_vs_nifty = xgb_result.total_return_pct - (
        nifty_result.total_return_pct if nifty_result else 0
    )

    verdict_color = "green" if spread_vs_random > 0 else "red"
    vs_random_str = f"[{verdict_color}]{spread_vs_random:+.2f}pp[/{verdict_color}]"
    v2_color = "green" if spread_vs_nifty > 0 else "red"
    vs_nifty_str = f"[{v2_color}]{spread_vs_nifty:+.2f}pp[/{v2_color}]"

    console.print()
    console.print(
        Panel(
            f"[bold]Alpha vs benchmarks[/bold]\n"
            f"  XGBoost vs Random:  {vs_random_str}\n"
            f"  XGBoost vs Nifty :  {vs_nifty_str}\n\n"
            f"[dim]Assumptions: equal-weight top-10, daily rebalance, intraday "
            f"open→close holding. No transaction costs modeled — real-world deductions "
            f"(STT, brokerage, slippage) typically cost 0.15-0.30%/round-trip.[/dim]",
            title="Backtest verdict",
            border_style="cyan",
        )
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
