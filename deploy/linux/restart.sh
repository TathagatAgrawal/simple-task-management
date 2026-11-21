#!/usr/bin/env bash
# Restart the task board, or only stop it with --stop.
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
assert_not_root

stop_app
if [ "${1:-}" = "--stop" ]; then
    echo "The task board is stopped."
else
    start_app
fi
