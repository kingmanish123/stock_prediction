# WhatsApp Automation — Setup Guide

End-to-end zero-effort automation. One-time setup, then the Mac runs everything on its own Monday-Saturday and sends WhatsApp alerts.

---

## What you get

| Time (IST) | Action | Gets you… |
|---|---|---|
| 6:50 AM (daily) | Upstox token check | ⚠️ WhatsApp if login needed |
| 7:45 AM (Mon-Fri) | News + predictions pipeline | ✅ 10 picks ready by 8:15 AM |
| 8:15 AM (Mon-Fri) | Morning picks | 📱 WhatsApp with Buy/Target/Stop for 10 stocks |
| 9:15 AM - 3:30 PM | Live monitor | 📱 WhatsApp on every BUY/TARGET/STOP/PARTIAL |
| 4:00 PM (Mon-Fri) | Validation | 📱 End-of-day P&L summary |
| Sun 9:00 PM | Weekly backtest | 📱 Weekly performance report |

---

## Prerequisites

- Node.js ≥ 18 (`which node` → `/usr/local/bin/node`)
- Mac Monday-Saturday always-on (settings → Battery → disable sleep when plugged in)
- WhatsApp account on your phone
- All existing stock-prediction-system setup complete (DB seeded, .venv created)

---

## One-time setup (10 minutes)

### Step 1 — Install Node deps (already done if you've run through the build)

```bash
cd whatsapp-bot
npm install
```

### Step 2 — Start bot interactively, scan QR

```bash
cd whatsapp-bot
node server.js
```

A QR code will print in your terminal. On your phone:
- Open WhatsApp
- Settings → **Linked Devices**
- **Link a Device** → scan the QR

You'll see `✓ WhatsApp bot connected`. Press **Ctrl+C** to stop.

The session is saved under `whatsapp-bot/auth_info/` — future starts are automatic, no QR needed.

### Step 3 — Set your phone number in `.env`

```bash
# Your full number with country code, no plus sign
WHATSAPP_NUMBER=919876543210
WHATSAPP_BOT_URL=http://127.0.0.1:3001
```

### Step 4 — Install launchd jobs

```bash
bash scripts/automation/install_automation.sh
```

This installs 7 scheduled jobs and starts the WhatsApp bot as a persistent daemon. Check with:

```bash
launchctl list | grep stockpredict
```

You should see 7 entries. Negative exit codes (e.g. `-9`) mean the job hasn't run yet — normal.

### Step 5 — Test each job manually

```bash
# Fire an end-of-day summary now (use today's date)
.venv/bin/python scripts/automation/eod_run.py

# You should receive a WhatsApp message within 10 seconds.
```

---

## Daily operations

### Normal day — you do nothing
6:50 AM: WhatsApp ping IF Upstox login needed (action: `python scripts/upstox_login.py`)
8:15 AM: 10 picks arrive. Decide which to trade.
9:15 AM-3:30 PM: BUY/TARGET/STOP alerts as they happen.
4:15 PM: EOD summary arrives.
Sunday 9 PM: Weekly report arrives.

### Manual overrides

**Stop the live monitor mid-day:**
```bash
pkill -f live_monitor.py
```

**Re-run morning pipeline (e.g. news was late):**
```bash
.venv/bin/python scripts/automation/morning_run.py
```

**Disable automation temporarily (vacation, etc.):**
```bash
bash scripts/automation/uninstall_automation.sh
```
(re-install later with `install_automation.sh` — sessions / auth preserved)

---

## Troubleshooting

### WhatsApp not arriving?

1. Bot health check:
   ```bash
   curl http://127.0.0.1:3001/health
   ```
   Should return `{"ok": true, "user": "919876543210:XX@s.whatsapp.net"}`.

2. Bot logs:
   ```bash
   tail -f logs/automation/whatsapp-bot.log
   ```

3. Manual re-login (if `"ok": false` or session expired):
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.stockpredict.whatsapp-bot.plist
   rm -rf whatsapp-bot/auth_info/
   cd whatsapp-bot && node server.js   # scan QR, Ctrl+C
   launchctl load ~/Library/LaunchAgents/com.stockpredict.whatsapp-bot.plist
   ```

### Morning pipeline didn't run?

```bash
tail -f logs/automation/morning.log
tail -f logs/automation/morning.err.log
```

Common causes:
- `.venv/bin/python` path wrong → edit `launchd/com.stockpredict.morning.plist`
- Upstox token expired → manual login fixes it
- Claude/Gemini API key missing → check `.env`

### Mac went to sleep — missed alerts?

macOS can put the Mac into `AppSleep` even when lid is open. Prevent this:

System Settings → Battery → **Prevent automatic sleeping when the display is off**

Or install `caffeinate` for market hours only:
```bash
# Add to the live-monitor plist as a wrapper:
/usr/bin/caffeinate -im /path/to/python scripts/live_monitor.py --whatsapp
```

---

## Costs

| Component | Cost |
|---|---|
| Electricity (Mac always-on) | ~₹50/month |
| Gemini API (bulk NLP) | ~₹500-700/month |
| Claude API (deep reasoning) | ~₹400-600/month |
| yfinance + Upstox market data | Free |
| WhatsApp / Baileys | Free |
| **Total** | **~₹1,000-1,400/month** |

---

## Architecture

```
launchd timers (macOS)
    ├─→ 6:50 AM   upstox_token_check.py
    ├─→ 7:45 AM   morning_run.py
    │             ├── run_ingestion.py (scrape news)
    │             ├── backfill_market_data.py (refresh OHLCV)
    │             ├── predict_today.py (10 picks)
    │             └── WhatsApp morning message
    ├─→ 9:15 AM   live_monitor.py (background, 30s refresh)
    │             └── On state change → WhatsApp alert
    ├─→ 3:35 PM   pkill live_monitor.py
    ├─→ 4:00 PM   eod_run.py
    │             ├── backfill_market_data.py (today's close)
    │             ├── validate_today.py
    │             └── WhatsApp EOD summary
    └─→ Sun 9 PM  weekly_run.py
                  ├── backtest_algo.py
                  └── WhatsApp weekly report

Baileys bot (persistent daemon)
    ← HTTP POST /send from any of the above
    → WhatsApp message to your phone
```

---

## What you still do manually

**Daily (5 min):**
1. **Morning:** Read the picks, decide which to trade based on your own intuition + risk appetite
2. **During market:** When alert fires, open broker app (Upstox/Zerodha) and place the order
3. **At target/stop:** Exit the position

**Weekly (2 min):**
- Read Sunday report
- If performance is poor, ask me to iterate on the algo

**Monthly:**
- Run `python scripts/fetch_fundamentals.py` (refresh P/E, ROE etc.)
- Review top performers / laggards, discuss adjustments

---

## Advanced — Auto-trading (future, NOT YET)

Upstox API supports order placement. Current plan stops at **alerts only**. If you want full auto later:

1. Prove the system works for 2+ months with alerts
2. Add `src/broker/upstox_trader.py` (place bracket orders)
3. Add Telegram-style button approvals in WhatsApp replies
4. Add risk guards: max daily loss, max position size, kill switch

This is a separate effort when you're ready.
