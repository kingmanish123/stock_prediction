#!/usr/bin/env bash
# Install launchd jobs for the stock prediction automation pipeline.
# Idempotent — safe to re-run.

set -euo pipefail

PROJECT_ROOT="/Users/apple/Documents/personal/Projects/Ideas/stock-prediction-system"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
SRC_DIR="$PROJECT_ROOT/launchd"

mkdir -p "$LAUNCH_AGENTS"
mkdir -p "$PROJECT_ROOT/logs/automation"

PLISTS=(
    "com.stockpredict.whatsapp-bot.plist"
    "com.stockpredict.upstox-check.plist"
    "com.stockpredict.morning.plist"
    "com.stockpredict.live-monitor.plist"
    "com.stockpredict.live-monitor-stop.plist"
    "com.stockpredict.eod.plist"
    "com.stockpredict.weekly.plist"
)

echo "▶ Installing ${#PLISTS[@]} launchd jobs..."
for plist in "${PLISTS[@]}"; do
    src="$SRC_DIR/$plist"
    dst="$LAUNCH_AGENTS/$plist"

    if [ ! -f "$src" ]; then
        echo "  ✗ MISSING: $src"
        continue
    fi

    # Unload if already loaded (ignore failure if not yet installed)
    launchctl unload "$dst" 2>/dev/null || true

    # Copy fresh
    cp "$src" "$dst"

    # Load
    if launchctl load "$dst" 2>&1; then
        echo "  ✓ Loaded $plist"
    else
        echo "  ✗ Failed to load $plist"
    fi
done

echo
echo "▶ Current status:"
launchctl list | grep stockpredict || echo "  (none — check for errors above)"

echo
echo "✓ Installation complete."
echo
echo "NEXT STEPS:"
echo "  1. Start the WhatsApp bot ONCE interactively to scan the QR code:"
echo "     cd $PROJECT_ROOT/whatsapp-bot && node server.js"
echo "     Scan the QR with your phone → WhatsApp → Linked Devices."
echo "     Then Ctrl+C. The launchd job will restart it and re-use the saved session."
echo
echo "  2. Set .env values:"
echo "     WHATSAPP_NUMBER=<your full number with country code, no +>"
echo "     WHATSAPP_BOT_URL=http://127.0.0.1:3001"
echo
echo "  3. Trigger the launchd jobs now to reload with env:"
echo "     bash $PROJECT_ROOT/scripts/automation/install_automation.sh"
