#!/usr/bin/env bash
# Uninstall all stock-prediction launchd jobs.
set -euo pipefail

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLISTS=(
    "com.stockpredict.whatsapp-bot.plist"
    "com.stockpredict.upstox-check.plist"
    "com.stockpredict.morning.plist"
    "com.stockpredict.live-monitor.plist"
    "com.stockpredict.live-monitor-stop.plist"
    "com.stockpredict.eod.plist"
    "com.stockpredict.weekly.plist"
)

for plist in "${PLISTS[@]}"; do
    dst="$LAUNCH_AGENTS/$plist"
    if [ -f "$dst" ]; then
        launchctl unload "$dst" 2>/dev/null || true
        rm -f "$dst"
        echo "  ✓ Removed $plist"
    fi
done

echo "✓ Uninstall complete. (auth_info/, DB, and logs preserved)"
