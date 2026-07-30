"""Continuous live monitor — runs during market hours and updates every 30s.

For each of today's 10 trade setups:
  - Fetches live price (Upstox if available, yfinance fallback)
  - Computes action: BUY / WAIT / MISSED ENTRY / TARGET HIT / STOP BROKEN
  - Updates Rich Live table in-place (screen doesn't scroll)
  - Logs alerts when state changes (e.g., price just hit target)

Usage:
    python scripts/live_monitor.py                  # today's picks
    python scripts/live_monitor.py --date 2026-04-23
    python scripts/live_monitor.py --refresh-sec 60
"""
import argparse
import signal
import sys
import time
from collections import deque
from datetime import date, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from sqlalchemy import select

from src.common import config
from src.common.logger import setup_logging
from src.db.models import MarketDataDaily, Prediction, Stock
from src.db.session import get_session
from src.notifications import templates as notif_templates
from src.notifications import whatsapp

# Risk/execution thresholds
GAP_UP_SKIP_PCT = 1.5         # if open > last_close * 1.015, skip (GAP_SKIP)
PARTIAL_BOOK_PCT = 0.5        # book 50% when live > entry * 1.005
MIN_VOL_CONFIRM_RATIO = 1.0   # require intraday volume >= 1.0× avg for BUY signal

# Upstox is optional
_UPSTOX_AVAILABLE = False
try:
    from src.broker.upstox_client import UpstoxClient
    if config.UPSTOX_ACCESS_TOKEN:
        _UPSTOX_AVAILABLE = True
except Exception:
    pass

setup_logging()
console = Console()

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)

# Action taxonomy
ACTION_BUY = "BUY"
ACTION_BUY_LOW_VOL = "BUY_LOW_VOL"     # price ok but volume weak → wait for volume confirmation
ACTION_WAIT = "WAIT"
ACTION_MISSED = "MISSED"
ACTION_GAP_SKIP = "GAP_SKIP"            # opened >1.5% above last close → don't chase
ACTION_PARTIAL = "PARTIAL"              # +0.5% reached → book 50%, trail rest
ACTION_TARGET = "TARGET"
ACTION_STOP = "STOP"
ACTION_PENDING = "PENDING"

ACTION_COLORS = {
    ACTION_BUY: "green bold",
    ACTION_BUY_LOW_VOL: "yellow bold",
    ACTION_WAIT: "yellow",
    ACTION_MISSED: "dim",
    ACTION_GAP_SKIP: "red",
    ACTION_PARTIAL: "cyan bold",
    ACTION_TARGET: "magenta bold",
    ACTION_STOP: "red bold",
    ACTION_PENDING: "cyan",
}

ACTION_ICONS = {
    ACTION_BUY: "🟢 BUY",
    ACTION_BUY_LOW_VOL: "🟡 BUY-LOWVOL",
    ACTION_WAIT: "⏸  WAIT",
    ACTION_MISSED: "⚪ MISSED",
    ACTION_GAP_SKIP: "🚫 GAP_SKIP",
    ACTION_PARTIAL: "💰 PARTIAL",
    ACTION_TARGET: "🎯 TARGET",
    ACTION_STOP: "🛑 STOP",
    ACTION_PENDING: "… PENDING",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=str, help="Predictions date (default: today in IST)")
    p.add_argument("--refresh-sec", type=int, default=30, help="Refresh interval in seconds")
    p.add_argument("--whatsapp", action="store_true",
                   help="Send WhatsApp alerts on BUY/TARGET/STOP/PARTIAL state changes")
    p.add_argument("--snapshot-interval-min", type=int, default=0,
                   help="Send periodic WhatsApp snapshot of all picks every N min (0=disabled)")
    return p.parse_args()


# State changes worth alerting on — only execute-now signals.
# BUY/BUY_LOW_VOL/PARTIAL appear in the periodic snapshots; sending them as
# standalone alerts adds noise and triggers WhatsApp rate limits on new
# linked-device sessions. Keep only TARGET (book profit) and STOP (cut loss).
ALERTABLE_ACTIONS = {ACTION_TARGET, ACTION_STOP}


def _ist_now() -> datetime:
    return datetime.now(IST)


def _is_market_open(now: datetime) -> bool:
    if now.weekday() >= 5:  # weekend
        return False
    t = now.time()
    return MARKET_OPEN <= t <= MARKET_CLOSE


def _load_picks(target_date: date) -> list[dict]:
    with get_session() as s:
        rows = s.execute(
            select(
                Prediction.buy_rank,
                Prediction.stock_id,
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

        picks = []
        for r in rows:
            # Last close before target_date = entry reference for gap check
            last_close_row = s.execute(
                select(MarketDataDaily.close, MarketDataDaily.volume)
                .where(
                    MarketDataDaily.stock_id == r.stock_id,
                    MarketDataDaily.trade_date < target_date,
                )
                .order_by(MarketDataDaily.trade_date.desc())
                .limit(1)
            ).first()
            last_close = float(last_close_row.close) if last_close_row and last_close_row.close else None

            # 20-day average volume for volume confirmation check
            vol_rows = s.execute(
                select(MarketDataDaily.volume)
                .where(
                    MarketDataDaily.stock_id == r.stock_id,
                    MarketDataDaily.trade_date < target_date,
                )
                .order_by(MarketDataDaily.trade_date.desc())
                .limit(20)
            ).all()
            volumes = [int(v.volume) for v in vol_rows if v.volume]
            avg_vol_20d = sum(volumes) / len(volumes) if volumes else None

            picks.append({
                "rank": r.buy_rank,
                "stock_id": r.stock_id,
                "symbol": r.symbol,
                "ticker": r.yfinance_ticker,
                "upstox_key": r.upstox_instrument_key,
                "predicted_low": float(r.predicted_low) if r.predicted_low else None,
                "predicted_high": float(r.predicted_high) if r.predicted_high else None,
                "last_close": last_close,
                "avg_vol_20d": avg_vol_20d,
                "open_today": None,
                "live": None,
                "live_volume": None,
                "last_action": ACTION_PENDING,
                "high_seen": None,
                "low_seen": None,
                "partial_booked": False,
            })
        return picks


def _fetch_quotes_upstox(picks: list[dict]) -> dict[str, dict]:
    """Batch Upstox quote for picks with an instrument_key."""
    keyed = [(p["symbol"], p["upstox_key"]) for p in picks if p.get("upstox_key")]
    if not keyed:
        return {}
    keys = [k for _, k in keyed]
    try:
        with UpstoxClient() as client:
            full = client.get_full_quote(keys)
    except Exception:
        return {}
    key_to_sym = {k: sym for sym, k in keyed}
    out: dict[str, dict] = {}
    for api_key, info in full.items():
        ik = info.get("instrument_token") or api_key.replace(":", "|")
        sym = key_to_sym.get(ik)
        if not sym:
            continue
        ohlc = info.get("ohlc", {}) or {}
        out[sym] = {
            "live": float(info["last_price"]) if info.get("last_price") is not None else None,
            "open": float(ohlc["open"]) if ohlc.get("open") is not None else None,
            "volume": int(info["volume"]) if info.get("volume") is not None else None,
        }
    return out


def _fetch_quote_yfinance(ticker: str) -> tuple[float | None, float | None]:
    """Return (open_today, live) via yfinance 1-day 1-min history."""
    try:
        t = yf.Ticker(ticker)
        try:
            live = float(t.fast_info.get("lastPrice") or 0) or None
        except Exception:
            live = None
        hist = t.history(period="1d", interval="1m")
        open_today = None
        if not hist.empty:
            open_today = float(hist["Open"].iloc[0])
            if live is None:
                live = float(hist["Close"].iloc[-1])
        return open_today, live
    except Exception:
        return None, None


def _decide_action(
    live: float | None,
    buy_at: float | None,
    target: float | None,
    stop: float | None,
    last_close: float | None = None,
    open_today: float | None = None,
    vol_ratio: float | None = None,
    partial_booked: bool = False,
) -> str:
    """Decide the current action given all context.

    Order of checks (early-exit):
      1. PENDING — missing live price
      2. GAP_SKIP — opened > last_close * (1 + GAP_UP_SKIP_PCT/100) → already ran away
      3. STOP hit
      4. TARGET hit
      5. PARTIAL — already above entry by 0.5% (book 50%) — once
      6. BUY_LOW_VOL / BUY — near entry
      7. WAIT — below entry
      8. MISSED — above entry by > 0.5% (already ran, no partial yet)
    """
    if live is None or buy_at is None or target is None or stop is None:
        return ACTION_PENDING

    # Gap-up skip — if market opened >1.5% above last close, don't chase
    if last_close is not None and open_today is not None:
        gap_open_pct = (open_today - last_close) / last_close * 100
        if gap_open_pct > GAP_UP_SKIP_PCT:
            # still honor TARGET/STOP if it actually hit the setup
            if live >= target:
                return ACTION_TARGET
            if live <= stop:
                return ACTION_STOP
            return ACTION_GAP_SKIP

    if live <= stop:
        return ACTION_STOP
    if live >= target:
        return ACTION_TARGET

    # Booking + trailing: once up 0.5% from entry, mark PARTIAL to remind user
    # to book half. After booking, rest continues — action flips to BUY again
    # (so further TARGET/STOP still fire on the remainder).
    move_from_entry_pct = (live - buy_at) / buy_at * 100
    if not partial_booked and move_from_entry_pct >= PARTIAL_BOOK_PCT:
        return ACTION_PARTIAL

    if abs(move_from_entry_pct) <= 0.5:
        # Price near entry — require volume confirmation
        if vol_ratio is not None and vol_ratio < MIN_VOL_CONFIRM_RATIO:
            return ACTION_BUY_LOW_VOL
        return ACTION_BUY

    if move_from_entry_pct < -0.5:
        return ACTION_WAIT
    return ACTION_MISSED


def _fetch_all_quotes(picks: list[dict]) -> None:
    """Populate live + open_today + volume for each pick, tracking high/low seen."""
    upstox = _fetch_quotes_upstox(picks) if _UPSTOX_AVAILABLE else {}
    for p in picks:
        uq = upstox.get(p["symbol"])
        if uq and uq.get("live") is not None:
            p["live"] = uq["live"]
            if uq.get("open") is not None:
                p["open_today"] = uq["open"]
            if uq.get("volume") is not None:
                p["live_volume"] = uq["volume"]
        else:
            ot, lv = _fetch_quote_yfinance(p["ticker"])
            if ot is not None:
                p["open_today"] = ot
            if lv is not None:
                p["live"] = lv

        if p["live"] is not None:
            p["high_seen"] = max(p["live"], p.get("high_seen") or p["live"])
            p["low_seen"] = min(p["live"], p.get("low_seen") or p["live"])


def _build_status_panel(
    target_date: date,
    now: datetime,
    refresh_sec: int,
    last_refresh_duration: float,
) -> Panel:
    source = "Upstox (real-time)" if _UPSTOX_AVAILABLE else "yfinance (delayed)"
    market_status = "[bold green]OPEN[/bold green]" if _is_market_open(now) else "[bold red]CLOSED[/bold red]"
    text = (
        f"[bold]Live Monitor — {target_date}[/bold]   "
        f"Time: {now.strftime('%H:%M:%S')} IST   "
        f"Market: {market_status}   "
        f"Source: {source}   "
        f"Refresh: {refresh_sec}s   "
        f"Last tick: {last_refresh_duration:.1f}s"
    )
    return Panel(text, border_style="cyan")


def _build_picks_table(picks: list[dict]) -> Table:
    tbl = Table(title="10 Active Setups", title_style="bold green", show_lines=False)
    tbl.add_column("#", style="dim", width=3)
    tbl.add_column("Symbol", style="cyan bold", width=11)
    tbl.add_column("Buy at", justify="right", width=11)
    tbl.add_column("Live", justify="right", style="bold", width=11)
    tbl.add_column("Move", justify="right", width=8)
    tbl.add_column("Target", justify="right", style="green", width=11)
    tbl.add_column("Stop", justify="right", style="red", width=11)
    tbl.add_column("to Tgt", justify="right", style="green", width=8)
    tbl.add_column("to Stop", justify="right", style="red", width=8)
    tbl.add_column("R:R live", justify="right", style="yellow", width=8)
    tbl.add_column("Action", justify="left", width=14)

    for p in picks:
        buy_at = p["open_today"] or p["last_close"] or p["predicted_low"]
        live = p["live"]
        target = p["predicted_high"]
        stop = p["predicted_low"]
        # Volume ratio: intraday live volume vs 20-day daily avg
        # (rough heuristic — live_volume is day's cumulative on Upstox;
        #  by EOD it would be full-day volume, so compare to avg_vol_20d.)
        vol_ratio = None
        if p.get("live_volume") and p.get("avg_vol_20d"):
            vol_ratio = p["live_volume"] / p["avg_vol_20d"]

        action = _decide_action(
            live, buy_at, target, stop,
            last_close=p.get("last_close"),
            open_today=p.get("open_today"),
            vol_ratio=vol_ratio,
            partial_booked=p.get("partial_booked", False),
        )

        def fmt_price(v):
            return f"₹{v:,.2f}" if v else "—"

        def fmt_pct(v):
            return f"{v:+.2f}%" if v is not None else "—"

        if live is not None and buy_at:
            move_pct = (live - buy_at) / buy_at * 100
        else:
            move_pct = None
        to_tgt_pct = ((target - live) / live * 100) if (live and target) else None
        to_stop_pct = ((live - stop) / live * 100) if (live and stop) else None
        rr_live = (to_tgt_pct / to_stop_pct) if (to_tgt_pct and to_stop_pct and to_stop_pct > 0) else 0

        action_color = ACTION_COLORS.get(action, "white")
        action_text = ACTION_ICONS.get(action, action)

        tbl.add_row(
            str(p["rank"]),
            p["symbol"],
            fmt_price(buy_at),
            fmt_price(live),
            fmt_pct(move_pct),
            fmt_price(target),
            fmt_price(stop),
            fmt_pct(to_tgt_pct),
            fmt_pct(to_stop_pct),
            f"{rr_live:.2f}" if rr_live else "—",
            f"[{action_color}]{action_text}[/{action_color}]",
        )
    return tbl


def _build_alerts_panel(alerts: deque) -> Panel:
    if not alerts:
        body = Text("(no alerts yet — waiting for state changes)", style="dim")
    else:
        lines = []
        for ts, symbol, old, new, detail in list(alerts)[-10:]:
            color = ACTION_COLORS.get(new, "white")
            lines.append(
                f"[dim]{ts.strftime('%H:%M:%S')}[/dim]  "
                f"[cyan bold]{symbol}[/cyan bold]  "
                f"{old} → [{color}]{new}[/{color}]  "
                f"[dim]{detail}[/dim]"
            )
        body = "\n".join(lines)
    return Panel(body, title="Alerts (most recent below)", border_style="yellow")


def _build_render(
    target_date: date,
    now: datetime,
    refresh_sec: int,
    last_refresh_duration: float,
    picks: list[dict],
    alerts: deque,
) -> Group:
    return Group(
        _build_status_panel(target_date, now, refresh_sec, last_refresh_duration),
        _build_picks_table(picks),
        _build_alerts_panel(alerts),
        Align.center(Text("Press Ctrl+C to exit", style="dim")),
    )


def main() -> int:
    args = parse_args()
    target_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date else _ist_now().date()
    )

    picks = _load_picks(target_date)
    if not picks:
        console.print(f"[red]No predictions for {target_date}. Run daily_run.py first.[/red]")
        return 1

    alerts: deque = deque(maxlen=50)
    # Dedup key = (symbol, action) — one WhatsApp ping per symbol per action per session
    whatsapp_sent: set[tuple[str, str]] = set()
    # Periodic snapshot bookkeeping
    last_snapshot_ts: datetime | None = None
    snapshot_interval_sec = args.snapshot_interval_min * 60 if args.snapshot_interval_min else 0

    # Graceful Ctrl+C
    stop_flag = {"stop": False}
    def _handler(*_):
        stop_flag["stop"] = True
    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    last_duration = 0.0

    with Live(
        _build_render(target_date, _ist_now(), args.refresh_sec, last_duration, picks, alerts),
        console=console,
        refresh_per_second=2,
    ) as live_view:
        while not stop_flag["stop"]:
            tick_start = time.time()
            _fetch_all_quotes(picks)
            last_duration = time.time() - tick_start

            # Detect state changes
            now = _ist_now()
            for p in picks:
                buy_at = p["open_today"] or p["last_close"] or p["predicted_low"]
                vol_ratio = None
                if p.get("live_volume") and p.get("avg_vol_20d"):
                    vol_ratio = p["live_volume"] / p["avg_vol_20d"]
                new_action = _decide_action(
                    p["live"], buy_at, p["predicted_high"], p["predicted_low"],
                    last_close=p.get("last_close"),
                    open_today=p.get("open_today"),
                    vol_ratio=vol_ratio,
                    partial_booked=p.get("partial_booked", False),
                )
                # Mark partial_booked so next tick flips back to BUY (rest of position)
                if new_action == ACTION_PARTIAL:
                    p["partial_booked"] = True

                if new_action != p["last_action"] and p["last_action"] != ACTION_PENDING:
                    detail = (
                        f"live ₹{p['live']:.2f}"
                        if p["live"] is not None else ""
                    )
                    alerts.append((now, p["symbol"], p["last_action"], new_action, detail))

                    # Fire WhatsApp on actionable state changes (dedup: once per symbol+action)
                    if args.whatsapp and new_action in ALERTABLE_ACTIONS:
                        key = (p["symbol"], new_action)
                        if key not in whatsapp_sent:
                            whatsapp_sent.add(key)
                            try:
                                msg = notif_templates.live_alert(
                                    symbol=p["symbol"],
                                    action=new_action,
                                    live_price=p["live"] or 0,
                                    entry=buy_at,
                                    target=p["predicted_high"],
                                    stop=p["predicted_low"],
                                )
                                whatsapp.send(msg)
                            except Exception:
                                pass
                p["last_action"] = new_action

            live_view.update(
                _build_render(target_date, now, args.refresh_sec, last_duration, picks, alerts)
            )

            # Periodic WhatsApp snapshot — all 10 picks with live prices + actions
            if args.whatsapp and snapshot_interval_sec > 0:
                should_snapshot = (
                    last_snapshot_ts is None
                    or (now - last_snapshot_ts).total_seconds() >= snapshot_interval_sec
                )
                if should_snapshot:
                    try:
                        snap_msg = notif_templates.live_snapshot(picks, now)
                        whatsapp.send(snap_msg)
                        last_snapshot_ts = now
                    except Exception:
                        pass

            # Sleep in small chunks so Ctrl+C responsive
            for _ in range(args.refresh_sec):
                if stop_flag["stop"]:
                    break
                time.sleep(1)

    # Exit summary
    console.print("\n[bold]Session summary[/bold]")
    buy_alerts = [a for a in alerts if a[3] == ACTION_BUY]
    target_alerts = [a for a in alerts if a[3] == ACTION_TARGET]
    stop_alerts = [a for a in alerts if a[3] == ACTION_STOP]
    console.print(f"  BUY signals fired: {len(buy_alerts)}")
    console.print(f"  TARGET hits      : {len(target_alerts)}")
    console.print(f"  STOP breaches    : {len(stop_alerts)}")
    console.print(f"  Total alerts     : {len(alerts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
