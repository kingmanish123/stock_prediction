"""Message templates for WhatsApp automation — plain text, emoji-friendly.

Keep each message under ~1500 chars (WhatsApp soft limit for single messages).
For longer reports, split into chunks and call send() multiple times.
"""
from __future__ import annotations

from datetime import date as DateT, datetime


def morning_picks(picks: list[dict], target_date: DateT, claude_cost_inr: float = 0.0) -> str:
    """picks = list of dicts with keys: rank, symbol, last_close, target, stop_loss, rr_ratio."""
    # NOTE: plain ASCII + emojis only — markdown stars get long messages dropped.
    header = f"🌅 Good morning - {target_date.strftime('%d %b %Y (%A)')}"
    lines = [header, "", "Today's 10 BUY setups:", ""]

    total_upside_pct = 0.0
    total_downside_pct = 0.0

    for p in picks:
        entry = p.get("last_close") or 0
        tgt = p.get("target") or p.get("predicted_high") or 0
        stop = p.get("stop_loss") or p.get("predicted_low") or 0
        rr = p.get("rr_ratio") or 0
        if entry and tgt and stop:
            up_pct = (tgt - entry) / entry * 100
            dn_pct = (entry - stop) / entry * 100
            total_upside_pct += up_pct
            total_downside_pct += dn_pct
            lines.append(
                f"{p['rank']}. {p['symbol']} @ Rs {entry:,.2f}"
                f"\n   Tgt Rs {tgt:,.2f}  Stop Rs {stop:,.2f}  RR {rr:.2f}"
            )
        else:
            lines.append(f"{p['rank']}. {p['symbol']} (price data unavailable)")

    if picks:
        avg_up = total_upside_pct / len(picks)
        avg_dn = total_downside_pct / len(picks)
        lines.append("")
        lines.append(f"💰 If all targets hit: +{total_upside_pct:.1f}% (avg {avg_up:+.2f}% per trade)")
        lines.append(f"🛑 If all stops hit: -{total_downside_pct:.1f}% (avg {avg_dn:+.2f}% per trade)")

    lines.append("")
    lines.append("Market opens 9:15 AM 📈")
    if claude_cost_inr > 0:
        lines.append(f"Analysis cost: Rs {claude_cost_inr:.2f}")

    return "\n".join(lines)


def no_picks_today(target_date: DateT, reason: str) -> str:
    return (
        f"⚠️ No picks for {target_date.strftime('%d %b %Y (%A)')}\n\n"
        f"Reason: {reason}\n\n"
        f"System will try again tomorrow morning."
    )


def live_alert(symbol: str, action: str, live_price: float, entry: float | None,
               target: float | None, stop: float | None, extra: str = "") -> str:
    """One-line alert during market hours — fire when state changes."""
    ts = datetime.now().strftime("%H:%M:%S")

    icons = {
        "BUY": "🟢", "BUY_LOW_VOL": "🟡", "PARTIAL": "💰",
        "TARGET": "🎯", "STOP": "🛑", "GAP_SKIP": "🚫", "MISSED": "⚪", "WAIT": "⏸",
    }
    titles = {
        "BUY": "BUY NOW", "BUY_LOW_VOL": "BUY (low volume, confirm first)",
        "PARTIAL": "PARTIAL — book 50%", "TARGET": "TARGET HIT — book profit",
        "STOP": "STOP — exit now", "GAP_SKIP": "GAP — skip today",
        "MISSED": "MISSED entry — don't chase", "WAIT": "WAIT — below entry",
    }
    icon = icons.get(action, "•")
    title = titles.get(action, action)

    lines = [f"{ts}  {icon} {title} - {symbol}"]
    lines.append(f"Live: Rs {live_price:,.2f}")
    if entry:
        move_pct = (live_price - entry) / entry * 100
        lines.append(f"Entry: Rs {entry:,.2f} ({move_pct:+.2f}% from entry)")
    if target:
        lines.append(f"Target: Rs {target:,.2f}")
    if stop:
        lines.append(f"Stop: Rs {stop:,.2f}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def live_snapshot(picks: list[dict], now: datetime) -> str:
    """Decision-ready snapshot grouped by action — sent every N min.

    FORMAT NOTES (debugged 2026-04-24):
      - No `*bold*` / `_italic_` markdown — WhatsApp silently drops such long
        messages from linked-device bots.
      - No em-dash (—), arrow (→), bullet (•) — ASCII only for max reliability.
      - Emojis are fine; they deliver consistently.
    """
    header = f"Live Update - {now.strftime('%H:%M IST')}"

    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        groups[p.get("last_action", "PENDING")].append(p)

    sections = [
        ("BUY", "🟢 BUY NOW - place order"),
        ("BUY_LOW_VOL", "🟡 BUY (low volume - confirm first)"),
        ("PARTIAL", "💰 BOOK 50% PROFIT now, trail rest"),
        ("TARGET", "🎯 TARGET HIT - SELL NOW"),
        ("STOP", "🛑 STOP BROKEN - EXIT NOW"),
        ("WAIT", "⏸  WAIT (below entry)"),
        ("MISSED", "⚪ MISSED (already ran)"),
        ("GAP_SKIP", "🚫 SKIP (gap invalidated)"),
        ("PENDING", "...  PENDING"),
    ]

    lines: list[str] = [header, ""]
    running_pnl = 0.0
    engaged = 0

    for action_key, title in sections:
        bucket = groups.get(action_key, [])
        if not bucket:
            continue
        lines.append(title)
        for p in bucket:
            sym = p["symbol"]
            live = p.get("live")
            entry = p.get("open_today") or p.get("last_close")
            target = p.get("predicted_high")
            stop = p.get("predicted_low")

            if live is None or entry is None:
                lines.append(f"  - {sym}  no data")
                continue

            move_pct = (live - entry) / entry * 100
            if action_key in ("BUY", "BUY_LOW_VOL"):
                lines.append(
                    f"  - {sym} Rs {live:,.2f}  tgt {target:,.2f} stop {stop:,.2f}"
                )
                running_pnl += move_pct
                engaged += 1
            elif action_key == "PARTIAL":
                lines.append(
                    f"  - {sym} Rs {live:,.2f} ({move_pct:+.2f}% from Rs {entry:,.2f})"
                )
                running_pnl += move_pct
                engaged += 1
            elif action_key == "TARGET":
                tgt_move = (target - entry) / entry * 100 if target else move_pct
                lines.append(
                    f"  - {sym} Rs {live:,.2f}  target Rs {target:,.2f} hit (+{tgt_move:.2f}%)"
                )
                running_pnl += tgt_move
                engaged += 1
            elif action_key == "STOP":
                stop_move = (stop - entry) / entry * 100 if stop else move_pct
                lines.append(
                    f"  - {sym} Rs {live:,.2f}  stop Rs {stop:,.2f} broken ({stop_move:+.2f}%)"
                )
                running_pnl += stop_move
                engaged += 1
            elif action_key == "WAIT":
                lines.append(
                    f"  - {sym} Rs {live:,.2f}  (entry Rs {entry:,.2f}, need {((entry-live)/live*100):+.2f}%)"
                )
            elif action_key == "MISSED":
                lines.append(
                    f"  - {sym} Rs {live:,.2f}  (+{move_pct:.2f}% above entry, skip)"
                )
            else:
                lines.append(f"  - {sym} Rs {live:,.2f}")
        lines.append("")

    if engaged > 0:
        emoji = "🟢" if running_pnl >= 0 else "🔴"
        lines.append(
            f"{emoji} Net PnL: {running_pnl:+.2f}%  ({engaged}/{len(picks)} active)"
        )
    else:
        lines.append("No active positions yet - waiting for entries.")

    return "\n".join(lines).rstrip()


def eod_summary(target_date: DateT, metrics: dict, trades: list[dict]) -> str:
    """End-of-day performance summary."""
    n = metrics.get("total_trades", 0)
    correct = metrics.get("direction_correct", 0)
    targets = metrics.get("target_hits", 0)
    stops = metrics.get("stop_hits", 0)
    holds = metrics.get("holds", 0)
    skipped = metrics.get("skipped", 0)
    total_pnl = float(metrics.get("total_pnl_pct", 0))
    rolling_pnl = metrics.get("rolling_7d_pnl_pct")
    rolling_acc = metrics.get("rolling_7d_accuracy")

    lines = [
        f"📊 End of day - {target_date.strftime('%d %b %Y (%A)')}",
        "",
        f"✓ Direction correct: {correct}/{n}",
        f"🎯 Target hits: {targets}",
        f"🛑 Stop hits: {stops}",
        f"⏸  Held to close: {holds}",
    ]
    if skipped:
        lines.append(f"🚫 Skipped (gap): {skipped}")

    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
    lines.append("")
    lines.append(f"{pnl_emoji} Total PnL: {total_pnl:+.2f}%")

    if trades:
        winners = [t for t in trades if t.get("pnl_pct", 0) > 0]
        losers = [t for t in trades if t.get("pnl_pct", 0) < 0]
        if winners:
            best = max(winners, key=lambda x: x["pnl_pct"])
            lines.append(f"📈 Best: {best['symbol']} {best['pnl_pct']:+.2f}%")
        if losers:
            worst = min(losers, key=lambda x: x["pnl_pct"])
            lines.append(f"📉 Worst: {worst['symbol']} {worst['pnl_pct']:+.2f}%")

    if rolling_pnl is not None or rolling_acc is not None:
        lines.append("")
        parts = []
        if rolling_pnl is not None:
            parts.append(f"PnL {float(rolling_pnl):+.2f}%")
        if rolling_acc is not None:
            parts.append(f"accuracy {float(rolling_acc):.0%}")
        lines.append(f"7-day rolling: {' | '.join(parts)}")

    return "\n".join(lines)


def weekly_summary(week_start: DateT, week_end: DateT, metrics: dict, top_insights: list[str]) -> str:
    """Sunday night weekly backtest report."""
    lines = [
        f"📊 Weekly report - {week_start.strftime('%d %b')} to {week_end.strftime('%d %b %Y')}",
        "",
        f"Trading days: {metrics.get('trading_days_covered', 0)}",
        f"Total trades: {metrics.get('total_trades', 0)}",
        f"Target hits: {metrics.get('target_hits', 0)}",
        f"Stop hits: {metrics.get('stop_hits', 0)}",
        f"Direction accuracy: {float(metrics.get('direction_accuracy', 0)):.0%}",
        "",
    ]

    total_pnl = float(metrics.get("total_pnl_pct", 0))
    avg_pnl = float(metrics.get("avg_pnl_pct", 0))
    sharpe = float(metrics.get("sharpe_ratio", 0))

    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
    lines.append(f"{pnl_emoji} Weekly PnL: {total_pnl:+.2f}%")
    lines.append(f"Avg per trade: {avg_pnl:+.3f}%")
    if sharpe:
        lines.append(f"Sharpe (annualized): {sharpe:.2f}")

    if top_insights:
        lines.append("")
        lines.append("Insights:")
        for ins in top_insights[:5]:
            lines.append(f"  - {ins}")

    return "\n".join(lines)


def upstox_token_warning() -> str:
    return (
        "⚠️ Upstox login reminder\n\n"
        "Daily token expires ~3:30 AM IST. Run:\n"
        "python scripts/upstox_login.py\n\n"
        "Do this before 9:15 AM so live monitor works."
    )


def pipeline_failed(stage: str, error: str) -> str:
    return (
        f"🚨 Pipeline failure: {stage}\n\n"
        f"Error: {error[:500]}\n\n"
        f"Check logs/automation/"
    )
