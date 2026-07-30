"""Single daily orchestrator — runs the full pre-market pipeline.

What it does, in order:
  1. Ingest fresh news + market data + macro + events (run_ingestion.py logic)
  2. Extract themes on any newly-fetched articles (extract_themes.py logic)
  3. Generate today's Top 10 BUY picks (predict_today.py logic)

This is the ONE command you run every morning around 8:00 AM IST.

Usage:
    python scripts/daily_run.py                     # default
    python scripts/daily_run.py --skip-ingestion    # if data already fresh
    python scripts/daily_run.py --skip-themes       # if themes already extracted
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.panel import Panel

console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--skip-ingestion", action="store_true")
    p.add_argument("--skip-themes", action="store_true")
    p.add_argument("--skip-prediction", action="store_true")
    p.add_argument("--ingestion-days", type=int, default=2,
                   help="Days of incremental data to pull")
    p.add_argument("--max-claude-candidates", type=int, default=15,
                   help="Cost control: max stocks to send to Claude")
    return p.parse_args()


def _run_step(name: str, cmd: list[str]) -> bool:
    """Run a child python script, stream output, return True if exit 0."""
    console.print()
    console.print(Panel.fit(f"[bold cyan]▶ {name}[/bold cyan]", border_style="cyan"))
    start = datetime.now()
    try:
        result = subprocess.run(cmd, check=False)
    except Exception as e:
        console.print(f"[red]Failed to launch: {e}[/red]")
        return False
    elapsed = (datetime.now() - start).total_seconds()
    if result.returncode == 0:
        console.print(f"[green]✓ {name} completed in {elapsed:.1f}s[/green]")
        return True
    console.print(f"[red]✗ {name} exited with code {result.returncode}[/red]")
    return False


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    python_bin = str(project_root / ".venv" / "bin" / "python")

    start = datetime.now()
    console.print(
        Panel.fit(
            f"[bold]Daily Pre-Market Run[/bold]\n"
            f"Start: {start.strftime('%Y-%m-%d %H:%M:%S')}",
            border_style="green",
        )
    )

    failures: list[str] = []

    # Step 1: Ingestion ───────────────────────────────────────────────
    if not args.skip_ingestion:
        ok = _run_step(
            "Step 1: Ingest fresh news + market data",
            [python_bin, "scripts/run_ingestion.py", "--days", str(args.ingestion_days)],
        )
        if not ok:
            failures.append("ingestion")
    else:
        console.print("[yellow]Skipping Step 1 (ingestion) per flag[/yellow]")

    # Step 2: Theme extraction ────────────────────────────────────────
    if not args.skip_themes:
        ok = _run_step(
            "Step 2: Extract themes on new articles (Gemini)",
            [python_bin, "scripts/extract_themes.py", "--rate-sec", "0.3"],
        )
        if not ok:
            failures.append("theme_extraction")
    else:
        console.print("[yellow]Skipping Step 2 (theme extraction) per flag[/yellow]")

    # Step 3: Prediction ──────────────────────────────────────────────
    if not args.skip_prediction:
        ok = _run_step(
            "Step 3: Generate Top 10 BUY picks (Claude reasoning)",
            [
                python_bin, "scripts/predict_today.py",
                "--max-claude-candidates", str(args.max_claude_candidates),
            ],
        )
        if not ok:
            failures.append("prediction")
    else:
        console.print("[yellow]Skipping Step 3 (prediction) per flag[/yellow]")

    # Summary ─────────────────────────────────────────────────────────
    total_elapsed = (datetime.now() - start).total_seconds()
    console.print()
    if failures:
        console.print(
            Panel.fit(
                f"[yellow]⚠ Completed with {len(failures)} failures: {', '.join(failures)}[/yellow]\n"
                f"Total elapsed: {total_elapsed:.1f}s",
                border_style="yellow",
            )
        )
        return 1

    console.print(
        Panel.fit(
            f"[bold green]✓ Daily run complete[/bold green]\n"
            f"Total elapsed: {total_elapsed:.1f}s\n\n"
            f"Check today's report: [cyan]reports/<target_date>.md[/cyan]",
            border_style="green",
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
