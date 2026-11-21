# shellcheck shell=bash

# Shared settings and helpers for the Linux scripts. Sourced, not run directly.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE="taskboard"
# shellcheck disable=SC2034  # used by update.sh and status.sh, which source this file
UPDATE_SERVICE="taskboard-update"
PORT=8000
HEALTH_URL="http://127.0.0.1:${PORT}/healthz"

get_uv() {
    if [ -x "$HOME/.local/bin/uv" ]; then
        echo "$HOME/.local/bin/uv"
    else
        command -v uv || true
    fi
}

app_healthy() {
    [ "$(curl -fsS --max-time 3 "$HEALTH_URL" 2>/dev/null | tr -d '[:space:]')" = "ok" ]
}

wait_healthy() {
    local seconds="${1:-60}" i
    for ((i = 0; i < seconds; i++)); do
        if app_healthy; then return 0; fi
        sleep 1
    done
    return 1
}

stop_app() {
    sudo systemctl stop "$SERVICE"
}

start_app() {
    sudo systemctl start "$SERVICE"
    if wait_healthy; then
        echo "The task board is running."
    else
        echo "The app did not start within a minute. Check: journalctl -u $SERVICE -n 50, and $APP_DIR/logs/app.log" >&2
    fi
}

assert_not_root() {
    if [ "$(id -u)" -eq 0 ]; then
        echo "Run this as your normal user, not root. It uses sudo where it needs to." >&2
        exit 1
    fi
}
