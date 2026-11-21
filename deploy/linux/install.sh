#!/usr/bin/env bash
# One-time setup of the task board on an Ubuntu/Debian server. Run as your normal user (not root)
# from a git checkout, e.g. ~/TaskBoard:
#   deploy/linux/install.sh
#
# It installs uv (which brings Python), installs the app's dependencies, optionally creates the
# first admin, registers a systemd service that starts the app at boot and restarts it if it
# crashes, and publishes it on the tailnet with `tailscale serve`.
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
assert_not_root
cd "$APP_DIR"
echo "== Setting up the task board in $APP_DIR =="

# 1. git and curl, then uv (Python manager; also installs Python 3.13 for the app)
sudo apt-get install -y git curl
uv="$(get_uv)"
if [ -z "$uv" ]; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv="$(get_uv)"
fi
if [ -z "$uv" ]; then
    echo "uv could not be found after installing it. Log in again and run this script again." >&2
    exit 1
fi
echo "Using uv at $uv"

# 2. App dependencies
"$uv" sync --no-dev

# 3. Settings file
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env. Edit BACKUP_DIR in it if backups should go somewhere other than $APP_DIR/backups."
fi

# 4. First admin
read -r -p "Create an admin account now? (y/n) " answer
if [ "$answer" = "y" ]; then
    "$uv" run --no-dev simple-task-management create-admin
fi

# 5. systemd service: start at boot, restart on crash
sed -e "s|@USER@|$USER|g" -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@UV@|$uv|g" -e "s|@PORT@|$PORT|g" \
    "$APP_DIR/deploy/linux/taskboard.service" | sudo tee "/etc/systemd/system/$SERVICE.service" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl restart "$SERVICE"
echo "Registered systemd service '$SERVICE'."
start_app

# 6. Publish on the tailnet with HTTPS
if command -v tailscale >/dev/null 2>&1; then
    sudo tailscale serve --bg "$PORT"
    sudo tailscale serve status
else
    echo "Tailscale was not found. Install it, then run: sudo tailscale serve --bg $PORT" >&2
fi

echo
echo "Done. Remaining manual steps:"
echo "  - Tailscale admin console -> Machines -> this server -> 'Disable key expiry'"
echo "  - Set BACKUP_DIR in $APP_DIR/.env to somewhere safe, then run deploy/linux/restart.sh"
echo "  - Keep copies of the backups off this server (see docs/operations.md)"
