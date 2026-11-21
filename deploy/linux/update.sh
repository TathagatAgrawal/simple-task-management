#!/usr/bin/env bash
# Update the task board to the latest version, keeping all of the firm's data. Run as your normal
# user (not root) from the app folder:
#
#   deploy/linux/update.sh
#
# Options:
#   --check                 Only say whether a newer version exists and what is new. Changes nothing.
#   --force                 Throw away local edits to the app's own files if they stop the update.
#
# Nightly updates (optional, off until you do this once):
#   --enable-auto-update    Set up a nightly systemd timer (default 03:00 IST, change it with --at 02:30).
#   --disable-auto-update   Remove the nightly timer.
# The timer runs this script with --auto. It always looks for a new version, but only installs it
# when an admin has turned on "Update automatically at night" in the app (user menu, Updates).
# Either way it leaves a note of what it did, which the app shows to admins, and logs to
# logs/update.log. It never asks questions and never uses --force. It needs passwordless sudo.
#
# What an update does: counts your data, takes a backup, gets the new code, installs its
# dependencies, starts the app (database changes are applied automatically on start, all or
# nothing), checks that the page loads, and counts your data again. If the new version will not
# start, it puts the previous version back.
set -Eeuo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# One line of Python (single quotes only, so it survives being passed on the command line).
SUMMARY_CODE="import sqlite3; from simple_task_management.config import load_settings; c = sqlite3.connect(load_settings().db_path); n = lambda t: c.execute('select count(*) from ' + t).fetchone()[0]; print('tasks=%d updates=%d people=%d schema=%d' % (n('tasks'), n('updates'), n('users'), c.execute('pragma user_version').fetchone()[0]))"

AUTO=0
BEFORE=""
BACKUP_PATH=""
uv=""

write_note() {
    # In --auto mode, leave a note the app can show to admins.
    local result="$1" detail="$2" data_dir
    data_dir="$("$uv" run --no-dev python -c "from simple_task_management.config import load_settings; print(load_settings().data_dir)" 2>/dev/null)" || return 0
    mkdir -p "$data_dir"
    RAN_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)" RESULT="$result" DETAIL="$detail" \
        "$uv" run --no-dev python -c "import json, os; print(json.dumps({'ran_at': os.environ['RAN_AT'], 'result': os.environ['RESULT'], 'detail': os.environ['DETAIL']}))" \
        >"$data_dir/update-last-run.json" || true
}

finish() {
    # finish CODE RESULT DETAIL: write the note (in --auto mode) and stop.
    trap - ERR
    if [ "$AUTO" = 1 ]; then write_note "$2" "$3"; fi
    exit "$1"
}

fail() {
    echo "The update stopped: $1" >&2
    finish 1 failed "$1"
}

get_summary() {
    # Prints "tasks=N updates=N people=N schema=N" read straight from the database, or nothing.
    "$uv" run --no-dev python -c "$SUMMARY_CODE" 2>/dev/null | tr -d '\r' || true
}

describe_summary() {
    local label="$1" line="$2"
    if [[ "$line" =~ tasks=([0-9]+)\ updates=([0-9]+)\ people=([0-9]+)\ schema=([0-9]+) ]]; then
        echo "$label: ${BASH_REMATCH[1]} tasks, ${BASH_REMATCH[2]} updates, ${BASH_REMATCH[3]} people (database version ${BASH_REMATCH[4]})"
    else
        echo "$label: could not read the database (this is normal on a brand-new install)."
    fi
}

restore_previous_version() {
    echo "The new version did not start. Putting the previous version back..."
    stop_app
    git reset --hard "$BEFORE" >/dev/null
    "$uv" sync --no-dev
    start_app
    if app_healthy; then
        echo "The previous version is running again. Your data was not changed."
    else
        echo "The previous version did not start either. Your data is safe in $APP_DIR/data." >&2
    fi
    if [ -n "$BACKUP_PATH" ]; then echo "The backup taken before this update: $BACKUP_PATH"; fi
    echo "Please send the last lines of $APP_DIR/logs/app.log to whoever looks after the app."
}

set_auto_update() {
    # set_auto_update on|off AT: install or remove the nightly systemd timer.
    local mode="$1" at="$2"
    if [ "$mode" = "off" ]; then
        if systemctl list-unit-files "$UPDATE_SERVICE.timer" 2>/dev/null | grep -q "$UPDATE_SERVICE.timer"; then
            sudo systemctl disable --now "$UPDATE_SERVICE.timer"
            sudo rm -f "/etc/systemd/system/$UPDATE_SERVICE.service" "/etc/systemd/system/$UPDATE_SERVICE.timer"
            sudo systemctl daemon-reload
            echo "Nightly updates are turned off on this server."
        else
            echo "Nightly updates were not set up on this server."
        fi
        return
    fi
    if ! sudo -n true 2>/dev/null; then
        echo "Warning: $USER needs passwordless sudo, because the nightly run restarts the service. It does not have it." >&2
    fi
    sudo tee "/etc/systemd/system/$UPDATE_SERVICE.service" >/dev/null <<UNIT
[Unit]
Description=Task board nightly update

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/deploy/linux/update.sh --auto
TimeoutStartSec=1h
UNIT
    sudo tee "/etc/systemd/system/$UPDATE_SERVICE.timer" >/dev/null <<UNIT
[Unit]
Description=Task board nightly update

[Timer]
OnCalendar=*-*-* $at:00 Asia/Kolkata
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$UPDATE_SERVICE.timer"
    echo "Nightly update timer '$UPDATE_SERVICE.timer' is set up for $at IST every day."
    echo "It only installs new versions while 'Update automatically at night' is turned on in the app (user menu, Updates)."
}

main() {
    local check_only=0 force=0 enable=0 disable=0 at="03:00"
    while [ $# -gt 0 ]; do
        case "$1" in
            --check) check_only=1 ;;
            --force) force=1 ;;
            --auto) AUTO=1 ;;
            --enable-auto-update) enable=1 ;;
            --disable-auto-update) disable=1 ;;
            --at) at="${2:?--at needs a time like 02:30}"; shift ;;
            *) echo "Unknown option: $1 (see the top of this script)" >&2; exit 2 ;;
        esac
        shift
    done

    assert_not_root
    cd "$APP_DIR"
    if [ "$disable" = 1 ]; then set_auto_update off "$at"; exit 0; fi
    if [ "$enable" = 1 ]; then set_auto_update on "$at"; exit 0; fi

    uv="$(get_uv)"
    if [ -z "$uv" ]; then echo "uv was not found. Run install.sh first." >&2; exit 1; fi
    if [ ! -d .git ]; then echo "This folder was not installed with git, so it cannot update itself." >&2; exit 1; fi

    if [ "$AUTO" = 1 ]; then
        mkdir -p "$APP_DIR/logs"
        exec > >(tee -a "$APP_DIR/logs/update.log") 2>&1
        echo "== Nightly update check, $(date '+%Y-%m-%d %H:%M') =="
    fi
    trap 'finish 1 failed "Unexpected error on line $LINENO of update.sh."' ERR

    # ---------------------------------------------------------------- 1. find the new version
    BEFORE="$(git rev-parse HEAD)"
    git fetch origin || fail "Could not reach GitHub (is the internet working?). Nothing was changed."
    local latest behind
    latest="$(git rev-parse origin/main)"
    behind="$(git rev-list --count HEAD..origin/main)"

    if [ "$BEFORE" = "$latest" ]; then
        echo "This server already has the latest version."
        finish 0 up-to-date "Already on the latest version (${latest:0:7})."
    fi
    echo "A newer version is available ($behind change(s)):"
    git log --oneline HEAD..origin/main
    if [ "$check_only" = 1 ]; then finish 0 available "$behind change(s) waiting."; fi

    if [ "$AUTO" = 1 ]; then
        local wanted
        wanted="$("$uv" run --no-dev simple-task-management update-setting 2>/dev/null | tr -d '[:space:]' || true)"
        if [ "$wanted" != "on" ]; then
            echo "Automatic updates are turned off in the app, so nothing was installed."
            finish 0 available "$behind change(s) waiting; automatic updates are off."
        fi
    fi

    local dirty can_ff=0
    dirty="$(git status --porcelain --untracked-files=no)"
    if [ -n "$dirty" ] && [ "$force" = 0 ]; then
        echo "These files in the app folder were edited on this server:"
        echo "$dirty"
        fail "Nothing was changed. If those edits are not needed, run the update again with --force."
    fi
    if git merge-base --is-ancestor HEAD origin/main; then
        can_ff=1
    elif [ "$force" = 0 ]; then
        fail "This copy of the app has history that the latest version does not. Nothing was changed. Run the update again with --force to replace the app's files with the latest version; your data and settings are kept."
    fi

    # ---------------------------------------------------------------- 2. protect the data
    echo
    local summary_before summary_after
    summary_before="$(get_summary)"
    describe_summary "Before" "$summary_before"

    echo "Taking a backup before updating..."
    local out
    out="$("$uv" run --no-dev simple-task-management backup --label pre-update)" || fail "The backup failed, so the update was cancelled. Nothing was changed."
    BACKUP_PATH="$(echo "$out" | sed -n 's/^Backup written to //p' | tail -n 1)"
    echo "Backup saved: $BACKUP_PATH"

    # ---------------------------------------------------------------- 3. install the new version
    stop_app
    if [ "$can_ff" = 1 ]; then
        git merge --ff-only origin/main || { start_app; finish 1 failed "Getting the new version failed; the current version was restarted."; }
    else
        git reset --hard origin/main
    fi

    if ! "$uv" sync --no-dev; then
        echo "Installing the new version's dependencies failed." >&2
        restore_previous_version
        finish 1 failed "Installing the new version's dependencies failed; the previous version was put back."
    fi

    # ---------------------------------------------------------------- 4. start it and check it
    start_app
    if ! app_healthy; then
        restore_previous_version
        finish 1 failed "The new version did not start; the previous version was put back."
    fi
    if ! { curl -fsS -o /dev/null --max-time 10 "http://127.0.0.1:$PORT/" && curl -fsS -o /dev/null --max-time 10 "http://127.0.0.1:$PORT/static/dist/app.js"; }; then
        echo "The app is running but its page did not load correctly." >&2
        restore_previous_version
        finish 1 failed "The page did not load after the update; the previous version was put back."
    fi

    # ---------------------------------------------------------------- 5. prove the data is all there
    echo
    summary_after="$(get_summary)"
    describe_summary "After " "$summary_after"
    if [ -n "$summary_before" ] && [ -n "$summary_after" ]; then
        if [ "${summary_before% schema=*}" = "${summary_after% schema=*}" ]; then
            if [ "${summary_before##* }" != "${summary_after##* }" ]; then
                echo "The database was upgraded from ${summary_before##*schema=} to ${summary_after##*schema=}."
            fi
            echo "All of your data is still there."
        else
            echo "WARNING: the counts above are different. Do not use the app. Restore the backup: $BACKUP_PATH" >&2
            finish 1 failed "The counts of tasks, updates or people changed. Restore the backup: $BACKUP_PATH"
        fi
    fi

    echo
    echo "Updated. Tell everyone to refresh the page once (Ctrl+F5), and to close and reopen the app if they added it to their phone's home screen."
    echo "If anything looks wrong, run:  git reset --hard $BEFORE   then restart.sh   (your data keeps working with the older version)."
    finish 0 updated "Now on $(git rev-parse --short HEAD) ($behind change(s)). Backup: $BACKUP_PATH"
}

# Everything above is function definitions, so Bash has read the whole script before it runs
# anything; an update that rewrites this file cannot confuse the run that is still in progress.
main "$@"
