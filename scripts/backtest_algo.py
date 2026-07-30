"""Backtest a named algo variant across a date range.

This is the iteration engine — each code change gets a new algo_name + version,
then you run this to measure it against historical days. Results land in
algo_experiments so you can compare variants side-by-side.

Flow for each date in range:
  1. Use EXISTING predictions + validations (algo variant is implicit in the code
     state at the time predictions were made)
  2. Simulate trade P&L using predicted_low (stop) / predicted_high (target) vs actuals
  3. Aggregate metrics across window
  4. Upsert one row in algo_experiments

Usage:
    # Record current state of system against last 5 days
    python scripts/backtest_algo.py --algo-name atr_stops_nifty500 --algo-version v1 \\
        --start 2026-04-20 --end 2026-04-24 \\
        --notes "Nifty 500 + ATR + TA + fundamentals"

    # Compare all past runs
    python scripts/backtest_algo.py --list
"""
import argparse
import json
import statistics
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table
from sqlalchemy import desc, select, text
from sqlalchemy.dialects.mysql import insert as mysql_insert

from src.common.logger import setup_logging
from src.db.models import AlgoExperiment, Prediction, Stock, Validation
from src.db.session import get_session

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--algo-name", type=str, help="Algo variant name")
    p.add_argument("--algo-version", type=str, help="Version tag (e.g. v1, 2026-04-24-a)")
    p.add_argument("--start", type=str, help="Start date YYYY-MM-DD")
    p.add_argument("--end", type=str, help="End date YYYY-MM-DD")
    p.add_argument("--notes", type=str, default="", help="Free-form notes")
    p.add_argument(
        "--config-file", type=str,
        help="Optional JSON file capturing the algo's config for reproducibility",
    )
    p.add_argument("--list", action="store_true", help="List all past algo experiments and exit")
    return p.parse_args()


def simulate(entry: float, act_h: float, act_l: float, act_c: float,
             target: float, stop: float) -> tuple[str, float]:
    """Return (outcome, pnl_pct). Same logic as validate_today._simulate_trade_pnl."""
    if entry <= stop:
        return "SKIP_GAP_DOWN", 0.0
    if entry >= target:
        return "SKIP_GAP_UP", 0.0
    stop_hit = act_l <= stop
    target_hit = act_h >= target
    if stop_hit and target_hit:
        return "AMBIGUOUS_STOP_FIRST", (stop - entry) / entry * 100
    if stop_hit:
        return "STOP", (stop - entry) / entry * 100
    if target_hit:
        return "TARGET", (target - entry) / entry * 100
    return "HOLD", (act_c - entry) / entry * 100


def run_backtest(
    algo_name: str,
    algo_version: str,
    start_dt: date,
    end_dt: date,
    config: dict,
    notes: str,
) -> dict:
    """Replay predictions in [start_dt, end_dt] and compute aggregate metrics."""
    with get_session() as s:
        rows = s.execute(
            select(
                Prediction.run_date,
                Stock.symbol,
                Prediction.buy_rank,
                Prediction.direction,
                Prediction.predicted_low,
                Prediction.predicted_high,
                Validation.actual_open,
                Validation.actual_high,
                Validation.actual_low,
                Validation.actual_close,
                Validation.direction_correct,
            )
            .join(Stock, Stock.id == Prediction.stock_id)
            .join(Validation, Validation.prediction_id == Prediction.id)
            .where(Prediction.run_date >= start_dt)
            .where(Prediction.run_date <= end_dt)
            .where(Prediction.buy_rank.isnot(None))
            .order_by(Prediction.run_date, Prediction.buy_rank)
        ).all()

    if not rows:
        console.print(f"[yellow]No validated predictions in {start_dt}→{end_dt}[/yellow]")
        return {}

    # Per-trade P&L
    trades: list[dict] = []
    for r in rows:
        if not (r.actual_open and r.actual_high and r.actual_low and r.actual_close
                and r.predicted_low and r.predicted_high):
            continue
        entry = float(r.actual_open)
        outcome, pnl = simulate(
            entry,
            float(r.actual_high), float(r.actual_low), float(r.actual_close),
            float(r.predicted_high), float(r.predicted_low),
        )
        trades.append({
            "date": str(r.run_date),
            "symbol": r.symbol,
            "outcome": outcome,
            "pnl_pct": pnl,
            "direction_correct": bool(r.direction_correct),
        })

    if not trades:
        return {}

    # Per-day roll-up
    per_day: dict[str, dict] = {}
    for t in trades:
        d = t["date"]
        per_day.setdefault(d, {"pnl": 0.0, "correct": 0, "total": 0})
        per_day[d]["pnl"] += t["pnl_pct"]
        per_day[d]["correct"] += 1 if t["direction_correct"] else 0
        per_day[d]["total"] += 1

    per_day_list = [
        {
            "date": d, "pnl_pct": round(v["pnl"], 4),
            "accuracy": round(v["correct"] / v["total"], 3) if v["total"] else 0,
            "trades": v["total"],
        }
        for d, v in sorted(per_day.items())
    ]

    # Aggregates
    total_trades = len(trades)
    direction_correct = sum(1 for t in trades if t["direction_correct"])
    targets = sum(1 for t in trades if t["outcome"] == "TARGET")
    stops = sum(1 for t in trades if t["outcome"] == "STOP")
    holds = sum(1 for t in trades if t["outcome"] == "HOLD")
    skipped = sum(1 for t in trades if "SKIP" in t["outcome"])
    pnls = [t["pnl_pct"] for t in trades]

    total_pnl = sum(pnls)
    avg_pnl = total_pnl / total_trades
    win_rate = sum(1 for p in pnls if p > 0) / total_trades

    # Rough daily Sharpe (if ≥2 days)
    daily_pnls = [v["pnl"] for v in per_day.values()]
    if len(daily_pnls) >= 2:
        std = statistics.stdev(daily_pnls)
        mean = statistics.mean(daily_pnls)
        sharpe = (mean / std * (252 ** 0.5)) if std > 0 else 0
    else:
        sharpe = 0

    # Max drawdown: running cumulative P&L, compute peak-to-trough
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = peak - cum
        max_dd = max(max_dd, dd)

    metrics = {
        "algo_name": algo_name,
        "algo_version": algo_version,
        "start_date": start_dt,
        "end_date": end_dt,
        "trading_days_covered": len(per_day),
        "config_json": config,
        "total_trades": total_trades,
        "direction_correct": direction_correct,
        "direction_accuracy": Decimal(str(round(direction_correct / total_trades, 3))),
        "target_hits": targets,
        "stop_hits": stops,
        "holds": holds,
        "skipped_gap": skipped,
        "total_pnl_pct": Decimal(str(round(total_pnl, 4))),
        "avg_pnl_pct": Decimal(str(round(avg_pnl, 4))),
        "win_rate": Decimal(str(round(win_rate, 3))),
        "sharpe_ratio": Decimal(str(round(sharpe, 3))),
        "max_drawdown_pct": Decimal(str(round(max_dd, 4))),
        "best_trade_pct": Decimal(str(round(max(pnls), 4))),
        "worst_trade_pct": Decimal(str(round(min(pnls), 4))),
        "per_day_results": per_day_list,
        "notes": notes,
    }
    return metrics


def persist(metrics: dict) -> int:
    with get_session() as s:
        stmt = mysql_insert(AlgoExperiment).values(metrics)
        update_cols = {k: stmt.inserted[k] for k in metrics if k not in (
            "algo_name", "algo_version", "start_date", "end_date"
        )}
        stmt = stmt.on_duplicate_key_update(**update_cols)
        s.execute(stmt)
        # Fetch id back
        exp = s.execute(
            select(AlgoExperiment.id)
            .where(
                AlgoExperiment.algo_name == metrics["algo_name"],
                AlgoExperiment.algo_version == metrics["algo_version"],
                AlgoExperiment.start_date == metrics["start_date"],
                AlgoExperiment.end_date == metrics["end_date"],
            )
        ).scalar()
    return int(exp) if exp else -1


def print_result(m: dict) -> None:
    t = Table(title=f"{m['algo_name']}@{m['algo_version']}  ({m['start_date']} → {m['end_date']})")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="green")

    def pct(x) -> str:
        return f"{float(x):+.3f}%"

    t.add_row("Trading days", str(m["trading_days_covered"]))
    t.add_row("Total trades", str(m["total_trades"]))
    t.add_row("Direction accuracy", f"{float(m['direction_accuracy']):.3f}")
    t.add_row("Target hits / Stops / Holds / Skipped",
              f"{m['target_hits']} / {m['stop_hits']} / {m['holds']} / {m['skipped_gap']}")
    t.add_row("Total P&L", pct(m["total_pnl_pct"]))
    t.add_row("Avg per trade", pct(m["avg_pnl_pct"]))
    t.add_row("Win rate", f"{float(m['win_rate']):.3f}")
    t.add_row("Sharpe (annualized)", f"{float(m['sharpe_ratio']):.3f}")
    t.add_row("Max drawdown", pct(m["max_drawdown_pct"]))
    t.add_row("Best / Worst trade",
              f"{pct(m['best_trade_pct'])} / {pct(m['worst_trade_pct'])}")
    console.print(t)

    dt = Table(title="Per-day breakdown")
    dt.add_column("Date", style="cyan")
    dt.add_column("Trades", justify="right")
    dt.add_column("Accuracy", justify="right")
    dt.add_column("P&L", justify="right", style="bold")
    for d in m["per_day_results"]:
        pnl_color = "green" if d["pnl_pct"] >= 0 else "red"
        dt.add_row(
            d["date"], str(d["trades"]),
            f"{d['accuracy']:.3f}",
            f"[{pnl_color}]{d['pnl_pct']:+.2f}%[/{pnl_color}]",
        )
    console.print(dt)


def list_experiments() -> None:
    with get_session() as s:
        rows = s.execute(
            select(AlgoExperiment).order_by(desc(AlgoExperiment.created_at)).limit(30)
        ).scalars().all()

    if not rows:
        console.print("[yellow]No experiments recorded yet[/yellow]")
        return

    t = Table(title="Algo experiments — latest 30")
    t.add_column("ID", style="dim")
    t.add_column("Name", style="cyan")
    t.add_column("Version", style="magenta")
    t.add_column("Window")
    t.add_column("Days", justify="right")
    t.add_column("Trades", justify="right")
    t.add_column("Acc", justify="right")
    t.add_column("Total P&L", justify="right", style="bold")
    t.add_column("Avg", justify="right")
    t.add_column("Sharpe", justify="right")
    for e in rows:
        pnl_color = "green" if (e.total_pnl_pct or 0) >= 0 else "red"
        t.add_row(
            str(e.id), e.algo_name, e.algo_version,
            f"{e.start_date}→{e.end_date}",
            str(e.trading_days_covered or 0), str(e.total_trades),
            f"{float(e.direction_accuracy or 0):.3f}",
            f"[{pnl_color}]{float(e.total_pnl_pct or 0):+.2f}%[/{pnl_color}]",
            f"{float(e.avg_pnl_pct or 0):+.3f}%",
            f"{float(e.sharpe_ratio or 0):.2f}",
        )
    console.print(t)


def main() -> int:
    args = parse_args()

    if args.list:
        list_experiments()
        return 0

    missing = [f for f in ("algo_name", "algo_version", "start", "end")
               if not getattr(args, f.replace("-", "_"))]
    if missing:
        console.print(f"[red]Missing required args: {missing}[/red]")
        return 1

    config = {}
    if args.config_file:
        config = json.loads(Path(args.config_file).read_text())

    start_dt = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(args.end, "%Y-%m-%d").date()

    metrics = run_backtest(args.algo_name, args.algo_version, start_dt, end_dt, config, args.notes)
    if not metrics:
        return 1

    exp_id = persist(metrics)
    console.print(f"[green]✓ Persisted as algo_experiments.id = {exp_id}[/green]\n")
    print_result(metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
