#!/usr/bin/env bash
# Check that everything the task board needs is running. Safe to run any time:
#   deploy/linux/status.sh
set -uo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ok=1

echo "systemd service '$SERVICE': $(systemctl is-active "$SERVICE" 2>/dev/null || true)"
if [ "$(systemctl is-active "$SERVICE" 2>/dev/null || true)" != "active" ]; then
    echo "  The service is not running. Try restart.sh, then check: journalctl -u $SERVICE -n 50"
    ok=0
fi

if systemctl is-enabled "$UPDATE_SERVICE.timer" >/dev/null 2>&1; then
    next="$(systemctl show "$UPDATE_SERVICE.timer" --property=NextElapseUSecRealtime --value 2>/dev/null || true)"
    echo "Nightly update timer '$UPDATE_SERVICE.timer': enabled, next run $next"
else
    echo "Nightly updates: not set up (optional). To set them up: deploy/linux/update.sh --enable-auto-update"
fi

if app_healthy; then
    echo "App health check ($HEALTH_URL): OK"
else
    echo "App health check ($HEALTH_URL): NOT RESPONDING. Try restart.sh, then check logs/app.log"
    ok=0
fi

if command -v tailscale >/dev/null 2>&1; then
    echo "Tailscale serve:"
    sudo tailscale serve status
else
    echo "Tailscale is not installed."
    ok=0
fi

backup_dir="$APP_DIR/backups"
if [ -f "$APP_DIR/.env" ]; then
    line="$(grep -E '^[[:space:]]*BACKUP_DIR[[:space:]]*=' "$APP_DIR/.env" | head -n 1 || true)"
    if [ -n "$line" ]; then
        value="$(echo "${line#*=}" | tr -d '"' | xargs)"
        case "$value" in
            /*) backup_dir="$value" ;;
            *) backup_dir="$APP_DIR/$value" ;;
        esac
    fi
fi
latest="$(ls -1 "$backup_dir"/tasks-*.db 2>/dev/null | sort | tail -n 1 || true)"
if [ -n "$latest" ]; then
    echo "Latest backup: $latest ($(date -r "$latest" '+%Y-%m-%d %H:%M'))"
else
    echo "No backups found in $backup_dir yet (the first one runs at 23:00)."
fi

echo "Memory: $(free -h | awk '/^Mem:/ {print $3 " used of " $2}'), swap: $(free -h | awk '/^Swap:/ {print $3 " used of " $2}')"

if [ "$ok" = 1 ]; then echo "All good."; else exit 1; fi
