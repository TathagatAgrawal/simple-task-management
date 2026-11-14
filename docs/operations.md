# Operations

How the app is deployed and kept running at the firm. Step-by-step instructions for whoever does the install are in the root [README.md](../README.md#deploying-to-the-firms-windows-pc). This page explains how the pieces fit together, for developers.

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

## Scripts (`deploy/windows/`)

All of them except `uninstall.ps1` dot-source `common.ps1`, which sets `$AppDir`, `$TaskName`, `$Port` and helpers such as `Get-UvPath`, `Test-AppHealthy`, `Stop-App` and `Start-App`.

| Script | Admin? | Does |
|---|---|---|
| `install.ps1` | Yes | Installs uv, runs `uv sync`, creates `.env`, optionally creates the first admin, registers the scheduled task (asks for the Windows password so it runs before login), starts the app, runs `tailscale serve`, and optionally disables sleep |
| `status.ps1` | No | Shows the scheduled task state, `/healthz`, `tailscale serve status` and the latest backup |
| `restart.ps1 [-Stop]` | Yes | Stops the task (and anything still listening on the port), then starts it again |
| `uninstall.ps1` | Yes | Asks for confirmation, removes the scheduled task (before stopping the app, so it can't restart), stops the app, offers a Desktop copy of the database, turns off `tailscale serve`, deletes the app folder, then optionally deletes backups, removes uv/Python and restores sleep. **Self-contained**: it doesn't load `common.ps1`, so it works on a half-deleted install when copied anywhere (`-AppDir` if not `C:\TaskBoard`) |
| `update.ps1` | Yes | Takes a backup, stops the app, runs `git pull --ff-only`, `uv sync`, and starts it again. Migrations run on startup |

These scripts can't run on macOS. CI parses them and runs PSScriptAnalyzer on `windows-latest`, but they have **not** been executed end-to-end in CI. Test changes on a real Windows machine.

## Security model

- **Reachability:** Uvicorn binds to `127.0.0.1`, so Windows Firewall needs no rules. The only route in is Tailscale Serve. Don't use Tailscale Funnel (public internet).
- **The shared Tailscale login** means anyone signed into it is on the tailnet. Mitigations: two-factor auth on that account, Device approval in the Tailscale admin console, and pruning old devices. App passwords are the second layer.
- **App auth:** scrypt-hashed passwords, 30-day session cookies (`HttpOnly`, `SameSite=Lax`, `Secure` over HTTPS), a per-session CSRF token on every POST, and a login throttle. Admin-only routes check `is_admin`.
- **Uvicorn** trusts `X-Forwarded-*` headers only from `127.0.0.1`, which is where Tailscale Serve proxies from.
- **Windows 10 is out of support.** The PC no longer gets security patches unless the firm pays for business ESU. Recommend using it only as the server. Moving the app to another machine means copying the folder and running `install.ps1`.

## Recovery

| Situation | Fix |
|---|---|
| App down | `status.ps1`, then `restart.ps1`, then read `logs\app.log` |
| PC rebooted / power cut | Nothing to do: the scheduled task and Tailscale (unattended) start at boot. Turn on "AC power recovery" in the BIOS if it's available |
| Only admin forgot their password | On the host: `uv run simple-task-management set-password <username>` |
| Bad data / need to roll back | `restart.ps1 -Stop`, copy a backup over `data\tasks.db`, `restart.ps1` |
| Remove the app completely | `uninstall.ps1`. If the folder was deleted while the app was running, copy `uninstall.ps1` onto the PC and run it from anywhere |
| Move to a new PC | Copy `C:\TaskBoard` (including `data\`), run `install.ps1` on the new PC, and rename the machine in Tailscale so the URL stays the same |

## Local "production-like" test on a Mac

```bash
DATA_DIR=demo-data uv run simple-task-management serve      # 127.0.0.1:8000
tailscale serve --bg 8000                                   # try it from another tailnet device
tailscale serve --https=443 off                             # stop publishing
```
