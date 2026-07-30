"""Live-price check against today's predicted trade setups.

Use during market hours:
  - Loads predictions for given date
  - Fetches CURRENT live price via yfinance
  - Shows: buy_at vs live, distance to target, distance to stop
  - Flags actionable setups (live ≈ buy_at, stop not broken)

Usage:
    python scripts/live_check.py --date 2026-04-23
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import select

from src.common import config
from src.common.logger import setup_logging
from src.db.models import Prediction, Stock
from src.db.session import get_session

# Prefer Upstox (real-time) when access token is configured; fall back to yfinance.
_UPSTOX_AVAILABLE = False
try:
    from src.broker.upstox_client import UpstoxClient
    if config.UPSTOX_ACCESS_TOKEN:
        _UPSTOX_AVAILABLE = True
except Exception:
    pass

setup_logging()
console = Console()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=str, required=True, help="Target date YYYY-MM-DD")
    return p.parse_args()


def _load_picks(target_date: date) -> list[dict]:
    with get_session() as s:
        rows = s.execute(
            select(
                Prediction.buy_rank,
                Stock.symbol,
                Stock.yfinance_ticker,
                Stock.upstox_instrument_key,
                Prediction.predicted_low,
                Prediction.predicted_high,
            )
            .join(Stock, Stock.id == Prediction.stock_id)
            .where(Prediction.run_date == target_date)
            .where(Prediction.buy_rank.isnot(None))
            .order_by(Prediction.buy_rank)
        ).all()

    return [{
        "rank": r.buy_rank,
        "symbol": r.symbol,
        "ticker": r.yfinance_ticker,
        "upstox_key": r.upstox_instrument_key,
        "predicted_low": float(r.predicted_low) if r.predicted_low else None,
        "predicted_high": float(r.predicted_high) if r.predicted_high else None,
    } for r in rows]


def _fetch_upstox_quotes(picks: list[dict]) -> dict[str, dict]:
    """Batch-fetch today's open + live LTP via Upstox for all picks with instrument_key.

    Returns {symbol: {'live': float|None, 'open': float|None}}.
    """
    keyed = [(p["symbol"], p.get("upstox_key")) for p in picks if p.get("upstox_key")]
    if not keyed:
        return {}
    keys = [k for _, k in keyed]
    try:
        with UpstoxClient() as client:
            full = client.get_full_quote(keys)
    except Exception as e:
        console.print(
            f"[yellow]Upstox quote fetch failed ({e}); falling back to yfinance.[/yellow]"
        )
        return {}

    key_to_symbol = {k: sym for sym, k in keyed}
    out: dict[str, dict] = {}
    for api_key, info in full.items():
        ik = info.get("instrument_token") or api_key.replace(":", "|")
        sym = key_to_symbol.get(ik)
        if not sym:
            continue
        ohlc = info.get("ohlc", {}) or {}
        out[sym] = {
            "live": float(info["last_price"]) if info.get("last_price") is not None else None,
            "open": float(ohlc["open"]) if ohlc.get("open") is not None else None,
        }
    return out


def _fetch_live_price(ticker: str) -> tuple[float | None, float | None]:
    """Return (open_today, live_price) via yfinance 1-day history."""
    try:
        t = yf.Ticker(ticker)
        # fast_info has real-time last price
        live = None
        try:
            live = float(t.fast_info.get("lastPrice") or 0) or None
        except Exception:
            pass
        # Today's open from 1-day history
        hist = t.history(period="1d", interval="1m")
        open_today = None
        if not hist.empty:
            open_today = float(hist["Open"].iloc[0])
            if live is None:
                live = float(hist["Close"].iloc[-1])
        return open_today, live
    except Exception as e:
        return None, None


def _classify_action(
    live: float, buy_at: float, target: float, stop: float
) -> tuple[str, str]:
    """Return (action_label, color). Pure math decision."""
    if live < stop:
        return "STOP BROKEN — avoid", "red"
    if live > target:
        return "past target — skip (no room)", "dim"
    gap_to_buy_pct = (live - buy_at) / buy_at * 100
    if abs(gap_to_buy_pct) <= 0.75:
        return "near entry ✓", "green"
    if gap_to_buy_pct < -2:
        return f"below entry by {abs(gap_to_buy_pct):.1f}% — wait or buy cheaper", "yellow"
    if gap_to_buy_pct > 2:
        return f"above entry by {gap_to_buy_pct:.1f}% — R:R degraded", "yellow"
    return f"gap {gap_to_buy_pct:+.1f}%", "white"


def main() -> int:
    args = parse_args()
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    picks = _load_picks(target_date)
    if not picks:
        console.print(f"[red]No predictions for {target_date}[/red]")
        return 1

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    quote_source = "Upstox (real-time)" if _UPSTOX_AVAILABLE else "yfinance (15-min delayed)"
    console.print(
        Panel.fit(
            f"[bold]Live Check — {target_date}[/bold]\n"
            f"Time: {now}\n"
            f"Quote source: {quote_source}\n"
            f"Fetching live prices for {len(picks)} picks…",
            border_style="cyan",
        )
    )

    # Try Upstox batched fetch first (1 API call for all stocks, real-time)
    upstox_quotes = _fetch_upstox_quotes(picks) if _UPSTOX_AVAILABLE else {}

    for p in picks:
        uq = upstox_quotes.get(p["symbol"])
        if uq and uq.get("live") is not None and uq.get("open") is not None:
            p["live"] = uq["live"]
            p["open_today"] = uq["open"]
        else:
            # Per-stock yfinance fallback
            open_today, live = _fetch_live_price(p["ticker"])
            p["live"] = live
            p["open_today"] = open_today
        p["buy_at"] = p["open_today"]

    tbl = Table(title=f"Live setup for {target_date}", title_style="bold cyan")
    tbl.add_column("#", style="dim")
    tbl.add_column("Symbol", style="cyan bold")
    tbl.add_column("Buy at", justify="right")
    tbl.add_column("Live", justify="right", style="bold")
    tbl.add_column("Gap", justify="right")
    tbl.add_column("Target", justify="right", style="green")
    tbl.add_column("to Target", justify="right", style="green")
    tbl.add_column("Stop", justify="right", style="red")
    tbl.add_column("to Stop", justify="right", style="red")
    tbl.add_column("R:R from live", justify="right", style="yellow")
    tbl.add_column("Action")

    actionable_count = 0
    for p in picks:
        buy_at = p.get("buy_at")
        live = p.get("live")
        target = p.get("predicted_high")
        stop = p.get("predicted_low")

        if not all([buy_at, live, target, stop]):
            tbl.add_row(
                str(p["rank"]), p["symbol"],
                "—", "—", "—", "—", "—", "—", "—", "—",
                "[red]no live data[/red]",
            )
            continue

        gap_pct = (live - buy_at) / buy_at * 100 if buy_at > 0 else 0
        to_target_pct = (target - live) / live * 100 if live > 0 else 0
        to_stop_pct = (live - stop) / live * 100 if live > 0 else 0
        rr_from_live = (to_target_pct / to_stop_pct) if to_stop_pct > 0 else 0

        label, color = _classify_action(live, buy_at, target, stop)
        if "near entry" in label:
            actionable_count += 1

        tbl.add_row(
            str(p["rank"]), p["symbol"],
            f"₹{buy_at:,.2f}",
            f"₹{live:,.2f}",
            f"{gap_pct:+.2f}%",
            f"₹{target:,.2f}",
            f"+{to_target_pct:.2f}%",
            f"₹{stop:,.2f}",
            f"-{to_stop_pct:.2f}%",
            f"{rr_from_live:.2f}",
            f"[{color}]{label}[/{color}]",
        )

    console.print(tbl)

    # Ranking: best setups RIGHT NOW (positive R:R from live + not broken stop + near entry)
    ranked = []
    for p in picks:
        live = p.get("live")
        target = p.get("predicted_high")
        stop = p.get("predicted_low")
        buy_at = p.get("buy_at")
        if not all([buy_at, live, target, stop]):
            continue
        if live < stop:
            continue  # stop broken, skip
        if live >= target:
            continue  # past target
        to_target_pct = (target - live) / live * 100 if live > 0 else 0
        to_stop_pct = (live - stop) / live * 100 if live > 0 else 0
        if to_stop_pct <= 0:
            continue
        rr_live = to_target_pct / to_stop_pct
        # Score: higher R:R is better; also prefer smaller gap from entry
        gap_abs = abs((live - buy_at) / buy_at) if buy_at > 0 else 1
        score = rr_live / (1 + gap_abs * 10)  # penalize being far from entry
        ranked.append({**p, "rr_live": rr_live, "gap_abs": gap_abs, "score": score})

    ranked.sort(key=lambda x: x["score"], reverse=True)
    if ranked:
        console.print()
        reco = Table(title="🎯 Best actionable setups RIGHT NOW (sorted by live R:R)", title_style="bold green")
        reco.add_column("Symbol", style="cyan bold")
        reco.add_column("Buy at open", justify="right")
        reco.add_column("Live", justify="right")
        reco.add_column("Target", justify="right", style="green")
        reco.add_column("Stop-loss", justify="right", style="red")
        reco.add_column("Live R:R", justify="right", style="yellow bold")
        for p in ranked[:5]:
            reco.add_row(
                p["symbol"],
                f"₹{p['buy_at']:,.2f}",
                f"₹{p['live']:,.2f}",
                f"₹{p['predicted_high']:,.2f}",
                f"₹{p['predicted_low']:,.2f}",
                f"{p['rr_live']:.2f}",
            )
        console.print(reco)
        console.print(
            f"\n[bold]Highest live R:R pick: [green]{ranked[0]['symbol']}[/green][/bold] "
            f"(R:R {ranked[0]['rr_live']:.2f} from current price ₹{ranked[0]['live']:,.2f})"
        )

    console.print(
        f"\n[dim]Market is dynamic — re-run this every 30 min to refresh. "
        f"Actionable near-entry picks: {actionable_count}.[/dim]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
