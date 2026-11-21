# Operations

How the app is deployed and kept running at the firm. Step-by-step instructions for whoever does the install are in the root [README.md](../README.md#deploying-to-the-firms-windows-pc) (Windows) and [below](#linux-server-deploylinux) (Linux). This page explains how the pieces fit together, for developers.

## Production shape

| Piece | Where / how |
|---|---|
| Host | One always-on **Windows 10** PC in the office |
| App folder | `C:\TaskBoard` (a git checkout or an unzipped release) |
| Python | Installed and managed by `uv` (`uv sync --no-dev`) |
| Process | Task Scheduler task **TaskBoard**: at startup, runs `uv run --no-dev simple-task-management serve --host 127.0.0.1 --port 8000` as a normal user, restarts every minute on failure, no time limit |
| HTTPS / network | `tailscale serve --bg 8000` publishes `https://<pc-name>.<tailnet>.ts.net` to the tailnet only. Tailscale must be in **Run unattended** mode, with key expiry disabled for this machine |
| Data | `data\tasks.db` (SQLite, WAL). **Never inside OneDrive or Google Drive**: sync tools can corrupt an open SQLite file |
| Backups | Nightly at 23:00 IST inside the app (`backup.nightly_loop`), using SQLite's online backup API, into `BACKUP_DIR` (ideally a cloud-synced folder). The newest 30 are kept. `update.ps1` also takes a `pre-update` backup |
| Logs | `logs\app.log`, rotated at midnight, 14 days kept |
| Config | `C:\TaskBoard\.env` (see `.env.example`); environment variables override it |

### Phones: install it as an app

Staff can put the app on their home screen so it opens full-screen with an icon: **iPhone** Safari → Share → *Add to Home Screen*; **Android** Chrome → ⋮ → *Install app* (or *Add to Home screen*). This needs no server setup beyond what's above, but Android only offers a real install over HTTPS, which `tailscale serve` provides. There is no offline mode, so Tailscale must be connected. On iPhone the installed app keeps its own sign-in, so each person signs in once more there.

**Notifications.** Staff are notified inside the app whenever someone else changes a task they're on. To also get alerts on a phone or computer, even when the board is closed, each person presses *Turn on alerts on this device* once per device (bell, then Settings) and chooses Allow; this needs the HTTPS address above. On an **iPhone or iPad** (iOS 16.4 or newer) the board must first be added to the Home Screen and opened from that icon. **Android** works with the app closed; a **desktop browser** works while the browser is running. A device that turned alerts on shows no popup inside the board, only the system's notification and the bell number.

Alerts are sent by Apple, Google or Mozilla's push services, so **the PC needs ordinary outbound internet** (it already has it for Tailscale); nothing is opened inward and the board stays private. Messages are encrypted for the device and the push services cannot read them, but they do see that a message was sent. People who don't want task names on a lock screen switch off *Show the task's name in alerts*. If a phone stops buzzing, check the PC is online, then turn alerts off and on again on the phone, and look in `logs\` for a line starting "Push to one device failed". The key the app signs pushes with is in the database, so it is backed up and moves with the data; setting `PUSH=0` in `.env` turns the feature off, and `PUSH_CONTACT` can hold a real contact address if a push service ever asks for one.

## Scripts (`deploy/windows/`)

All of them except `uninstall.ps1` dot-source `common.ps1`, which sets `$AppDir`, `$TaskName`, `$Port` and helpers such as `Get-UvPath`, `Test-AppHealthy`, `Stop-App` and `Start-App`.

| Script | Admin? | Does |
|---|---|---|
| `install.ps1` | Yes | Installs uv, runs `uv sync`, creates `.env`, optionally creates the first admin, registers the scheduled task (asks for the Windows password so it runs before login), starts the app, runs `tailscale serve`, and optionally disables sleep |
| `status.ps1` | No | Shows the scheduled task state, `/healthz`, `tailscale serve status` and the latest backup |
| `restart.ps1 [-Stop]` | Yes | Stops the task (and anything still listening on the port), then starts it again |
| `uninstall.ps1` | Yes | Asks for confirmation, removes the scheduled task (before stopping the app, so it can't restart), stops the app, offers a Desktop copy of the database, turns off `tailscale serve`, deletes the app folder, then optionally deletes backups, removes uv/Python and restores sleep. **Self-contained**: it doesn't load `common.ps1`, so it works on a half-deleted install when copied anywhere (`-AppDir` if not `C:\TaskBoard`) |
| `update.ps1` | Yes | Counts the data, takes a backup, gets the latest version (git, or `-ZipPath` for a folder without git), installs dependencies, starts the app, checks the page loads, and counts the data again. Puts the previous version back if the new one won't start. `-CheckOnly` just reports what's new; `-Force` replaces the app's own files if local edits or a different history stop the update. `-EnableAutoUpdate` / `-DisableAutoUpdate` set up or remove the nightly task. See "Updating the app" below |

These scripts can't run on macOS. CI parses them and runs PSScriptAnalyzer on `windows-latest`, but they have **not** been executed end-to-end in CI. Test changes on a real Windows machine.

## Linux server (`deploy/linux/`)

The same app runs on an Ubuntu VM (for example a small DigitalOcean Droplet) with the same shape as the Windows PC: one process on `127.0.0.1:8000`, `tailscale serve` for HTTPS, SQLite under `data/`, and the app's own nightly backup. The scripts are bash and mirror the Windows ones; they are run as a normal user (not root) with passwordless `sudo`, from a git checkout such as `~/TaskBoard`.

| Piece | Where / how |
|---|---|
| Process | systemd service **taskboard**, written from `deploy/linux/taskboard.service` by `install.sh`: starts at boot, `Restart=always`, runs as the installing user |
| Update timer | Optional `taskboard-update.timer` (daily 03:00 IST) runs `update.sh --auto` as a oneshot service. It is created by `update.sh --enable-auto-update` and removed by `--disable-auto-update`. The admins' switch in the app still decides whether anything is installed |
| Logs | `logs/app.log` as on Windows, plus `journalctl -u taskboard` for crashes before the app's own logging starts |
| Network | No inbound ports at all: close SSH in the cloud firewall once Tailscale SSH works. `tailscale serve --bg 8000` is the only way in, and the machine needs key expiry disabled in the Tailscale admin console |

| Script | Does |
|---|---|
| `install.sh` | Installs git, curl and uv, runs `uv sync --no-dev`, creates `.env`, optionally creates the first admin, writes and enables the systemd service, starts it and runs `tailscale serve` |
| `status.sh` | Shows the service state, the update timer, `/healthz`, `tailscale serve status`, the latest backup and memory/swap use |
| `restart.sh [--stop]` | Restarts the service, or only stops it |
| `update.sh` | The same steps as `update.ps1` (count the data, take a `pre-update` backup, fast-forward to `origin/main`, `uv sync`, start, check the page, count again, roll back if the new version won't start). Options: `--check`, `--force`, `--enable-auto-update [--at HH:MM]`, `--disable-auto-update`. Git checkouts only; there is no ZIP mode. The whole script is one `main` function so an update that rewrites it can't confuse the run in progress |

A private repository needs a way for the server to `git fetch`: either a read-only **deploy key** (`ssh-keygen -t ed25519`, add the public key under the repository's Settings, Deploy keys, and clone with the `git@github.com:` address) or an HTTPS clone with a fine-grained read-only token. The app's own update check uses the same `origin`.

**Backups are on the same disk as the data unless you move them.** The nightly backup goes to `BACKUP_DIR` on the server, which protects against a bad update or a deleted task but not against losing the VM. Turn on the provider's snapshots (DigitalOcean's weekly Backups cost about 20% more) or copy `backups/` somewhere else on a schedule.

**Memory.** The app itself uses roughly 75 to 150 MB. On a 512 MB or 1 GB VM add a 1 to 2 GB swapfile before the first `apt upgrade` or `uv sync`, which can briefly use far more than the app does.

Like the Windows scripts, these are checked in CI (`bash -n` and ShellCheck) and covered by a manual test of the update and roll-back paths against a local git remote, but they are not run end-to-end in CI.

## Security model

- **Reachability:** Uvicorn binds to `127.0.0.1`, so Windows Firewall needs no rules. The only route in is Tailscale Serve. Don't use Tailscale Funnel (public internet).
- **The shared Tailscale login** means anyone signed into it is on the tailnet. Mitigations: two-factor auth on that account, Device approval in the Tailscale admin console, and pruning old devices. App passwords are the second layer.
- **App auth:** scrypt-hashed passwords, 30-day session cookies (`HttpOnly`, `SameSite=Lax`, `Secure` over HTTPS), a per-session CSRF token on every POST, and a login throttle. Admin-only routes check `is_admin`.
- **Uvicorn** trusts `X-Forwarded-*` headers only from `127.0.0.1`, which is where Tailscale Serve proxies from.
- **Windows 10 is out of support.** The PC no longer gets security patches unless the firm pays for business ESU. Recommend using it only as the server. Moving the app to another machine means copying the folder and running `install.ps1`.

## Updating the app

Run `update.ps1` in an Administrator PowerShell on the PC (steps in the root README). **It never deletes or replaces the data**: `data\`, `backups\`, `logs\` and `.env` are outside what an update touches, and the app is not reinstalled.

1. **Before changing anything** it reads the database and prints how many tasks, updates and people there are, then takes a backup labelled `pre-update`. If the backup fails, the update is cancelled.
2. **It gets the new code** (`git fetch` and fast-forward, or the files from a ZIP), installs the Python dependencies with `uv sync --no-dev`, and starts the app. No Node or build tools are needed on the PC: the web client is a built file committed to the repository.
3. **The database upgrades itself on start** (`db.migrate`): each step runs in one transaction, so a step either applies completely or leaves the database exactly as it was. Old data is kept as it is; new tables start empty (for example, there are no notifications until someone changes a task, and everyone's notification settings start at the default).
4. **It checks the result**: the app answers `/healthz`, the page and the client file load, and the counts match what it printed before. If the new version doesn't start, it puts the previous code back and starts that. The previous version runs fine on an upgraded database, so a rollback never needs the data restored.
5. Everyone refreshes the page once (Ctrl+F5); an already-open tab keeps running the old page until it does.

**Existing tasks and notifications.** The first start after updating from a version without notifications runs a one-time backfill (migration 3 to 4): everyone on an open task gets one unread, bell-only notification for it ("assigned you to this task", dated when they were added), so existing work appears in the bell right away without any pop-up. See [data-model.md](data-model.md#migrations).

### Seeing that an update is waiting, and updating by itself

- **The app looks for updates.** Every `UPDATE_CHECK_HOURS` (6) hours, and when an admin presses *Check now*, the app runs `git fetch` and compares. Admins see "A newer version is available" with the changes in the user menu, under *Updates*. Looking changes no files. It needs git and a copy installed with git; otherwise the window says it can't look. Set `UPDATE_CHECK=0` in `.env` to turn the looking off.
- **Updating by itself is opt-in, in two parts.** (1) Once on the PC, run `update.ps1 -EnableAutoUpdate` (an Administrator PowerShell; it asks for the Windows password, like `install.ps1`, so the task can run when nobody is signed in). That registers the `TaskBoardUpdate` task, daily at 03:00 (`-At 02:30` to change it). (2) An admin turns on *Update automatically at night* in the app's Updates window. The nightly run always looks, but only installs while that switch is on. It never asks questions and never uses `-Force`, so local edits or a different history make it stop and say so instead of overwriting anything.
- **What it leaves behind.** `logs\update.log` has the full output, and `data\update-last-run.json` holds a one-line note (`up-to-date`, `available`, `updated` or `failed`, with detail) that the Updates window shows to admins. `status.ps1` shows whether the nightly task exists.
- **Why the app doesn't install updates itself.** Installing stops and restarts the app and replaces its own files, which needs an administrator and a supervisor to put the old version back if the new one fails. The scheduled script has both; a button inside the running app would not. Turn the nightly task off with `update.ps1 -DisableAutoUpdate`.

If the counts ever differ, or something looks wrong later, restore the `pre-update` backup (see Recovery). The update's last line tells you the exact commit to return to with `git reset --hard`.

## Recovery

| Situation | Fix |
|---|---|
| App down | `status.ps1`, then `restart.ps1`, then read `logs\app.log` |
| PC rebooted / power cut | Nothing to do: the scheduled task and Tailscale (unattended) start at boot. Turn on "AC power recovery" in the BIOS if it's available |
| Only admin forgot their password | On the host: `uv run simple-task-management set-password <username>` |
| Bad data / need to roll back | `restart.ps1 -Stop`, copy a backup over `data\tasks.db`, `restart.ps1`. A `pre-update` backup restored into a newer version upgrades itself again on start |
| An update failed halfway | `update.ps1` already put the previous version back and says so. If not: `git reset --hard <the commit it printed>`, `uv sync --no-dev`, `restart.ps1`. The data is unchanged unless a migration fully succeeded, and the older version works on it either way |
| Remove the app completely | `uninstall.ps1`. If the folder was deleted while the app was running, copy `uninstall.ps1` onto the PC and run it from anywhere |
| Move to a new PC | Copy `C:\TaskBoard` (including `data\`), run `install.ps1` on the new PC, and rename the machine in Tailscale so the URL stays the same |
| Move to a Linux VM | Clone the repo, run `deploy/linux/install.sh`, stop the old app, copy `data/tasks.db` (plus any `-wal` and `-shm` files next to it) over the new one with the service stopped, then `restart.sh`. The push signing key lives in the database, so devices keep working. Only one copy should run at a time |

## Local "production-like" test on a Mac

```bash
DATA_DIR=demo-data uv run simple-task-management serve      # 127.0.0.1:8000
tailscale serve --bg 8000                                   # try it from another tailnet device
tailscale serve --https=443 off                             # stop publishing
```
