# Simple Task Management

A one-page task board for a three-person CA firm. Tasks have one or more assignees, a due date, an optional repeat schedule (weekly, monthly, quarterly, yearly) and a thread of updates. Everyone sees what's overdue, due today and due in the next three days. Cards move between To do / Doing / Done by drag-and-drop. One admin can add and remove people. Light, dark and system themes.

It's a small FastAPI + SQLite app with server-rendered HTML and htmx — no build step, no Node, no separate database server. It runs on one always-on Windows PC and staff reach it privately over Tailscale.

**Developers and AI agents: start at [`docs/README.md`](docs/README.md)** for the structure, design philosophy and conventions. The original design plan, with diagrams and mockups, is [`docs/design/plan.html`](docs/design/plan.html) (open it in a browser).

## Try it on your Mac

You need [uv](https://docs.astral.sh/uv/) (`brew install uv`). It installs the right Python automatically.

```bash
uv sync

# Use a throwaway data folder so demo data never mixes with real data
export DATA_DIR=demo-data BACKUP_DIR=demo-backups LOG_DIR=demo-logs

uv run simple-task-management seed-demo     # 3 people + realistic tasks
uv run simple-task-management serve          # http://127.0.0.1:8000
```

Sign in as `asha` (admin), `ravi` or `meera`. The demo password is printed by `seed-demo`. Delete the `demo-*` folders to start over (they're git-ignored).

### A pre-shipping checklist

Work through this before handing it to the firm:

1. **Two people at once.** Open a second browser (or a private window) and sign in as `ravi`. Move a card as Asha; Ravi's board catches up within 60 seconds, or immediately when that window regains focus.
2. **Drag-and-drop.** Drag cards between columns in Chrome, Edge and Safari. Each column stays sorted by due date.
3. **Recurring tasks.** Drag the monthly "GSTR-3B" card to Done. A new card for next month appears in To do, and both threads link to each other (`#id` links).
4. **Multiple assignees.** Open a task and toggle people on and off. The thread logs "added / removed". Use the "Showing" filter to check each person's view and "Unassigned".
5. **Themes.** User menu → Theme → Light / Dark / System. Sign in as the same person in another browser: the choice follows them.
6. **People admin.** As Asha, Manage people → add someone → sign in with the temporary password in a private window → you're asked to set a new password. Try removing them and resetting a password.
7. **Over Tailscale from another device.** With Tailscale running on your Mac, run `tailscale serve --bg 8000`, then open the `https://<your-mac>.<tailnet>.ts.net` URL it prints from another device on your tailnet. Turn it off afterwards with `tailscale serve --https=443 off`.
8. **Backups.** `uv run simple-task-management backup` writes a copy into `BACKUP_DIR`. Open it with `sqlite3 demo-backups/tasks-*.db "select count(*) from tasks"`.
9. **Restore.** Stop the server, copy a backup over `demo-data/tasks.db`, start it again and check the board.

## Development

```bash
uv run pytest                      # tests
uv run ruff check .                # lint (includes docstring checks)
uv run ruff format .               # format
uv run simple-task-management serve --reload   # auto-restart on code changes
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs on every push and pull request:

- **Lint and format**: `ruff check` and `ruff format --check`.
- **Tests** on Ubuntu, Windows (what the firm runs) and macOS (where it's developed).
- **Windows scripts**: every `deploy/windows/*.ps1` is parsed and run through PSScriptAnalyzer, since they can't be executed on a Mac.

### How it's put together

| File | What it does |
|---|---|
| `src/simple_task_management/app.py` | FastAPI routes: the one page plus the HTML fragments htmx swaps in |
| `store.py` | All SQL for tasks, assignees, updates and people; every change writes a history event in the same transaction |
| `recurrence.py` | Next-due-date arithmetic (month-end anchoring) |
| `dates.py` | "Today" in IST, summary buckets, labels |
| `auth.py` | scrypt password hashing, sessions, login throttle |
| `backup.py` | Online SQLite backups, retention, the nightly loop |
| `db.py`, `schema.sql` | Connection pragmas and migrations (`PRAGMA user_version`) |
| `__init__.py` | The CLI: `serve`, `create-admin`, `set-password`, `backup`, `seed-demo` |
| `templates/`, `static/` | Jinja templates, CSS (light/dark variables), htmx, and ~220 lines of JS for drag-and-drop, the task drawer and dialogs |

## Deploying to the firm's Windows PC

Full background is in section 10 of the design plan. In short, on the Windows 10 PC that will host it:

1. Copy this folder to `C:\TaskBoard` (with `git clone`, or download the repo as a ZIP and unzip it there).
2. Open **PowerShell as Administrator** and run:

   ```powershell
   cd C:\TaskBoard
   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
   ```

   It installs uv and Python, installs the app, creates the first admin, registers a **TaskBoard** scheduled task that starts the app at boot (before anyone signs in) and restarts it if it crashes, and runs `tailscale serve --bg 8000`. It asks for the Windows account's password once, so the task can run while nobody is logged in.
3. Do the manual steps it prints at the end: Tailscale **Run unattended**, **Disable key expiry** for this PC in the Tailscale admin console, Windows Update active hours, and set `BACKUP_DIR` in `C:\TaskBoard\.env` to a OneDrive or Google Drive folder (then run `restart.ps1`).
4. Because the whole firm shares one Tailscale login, turn on two-factor authentication for it and **Device approval** in the Tailscale admin console.

### Day-to-day scripts (Administrator PowerShell, from `C:\TaskBoard`)

| Script | Use it to |
|---|---|
| `deploy\windows\status.ps1` | Check the app, Tailscale and the latest backup |
| `deploy\windows\restart.ps1` | Restart the app (`-Stop` to just stop it) |
| `deploy\windows\update.ps1` | Back up, pull the new version, reinstall, restart |

### Restoring a backup

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\restart.ps1 -Stop
copy "<BACKUP_DIR>\tasks-2026-11-14-230000.db" C:\TaskBoard\data\tasks.db
powershell -ExecutionPolicy Bypass -File deploy\windows\restart.ps1
```

If the only admin forgets their password: `uv run simple-task-management set-password <username>` on the host PC.

## For the staff

1. Make sure Tailscale is running on your computer.
2. Open **https://tasks.\<your-tailnet\>.ts.net** and bookmark it. In Chrome or Edge you can also use ⋮ → Cast, save and share → **Install page as app** to give it its own window.
3. Sign in with the username and temporary password the admin gives you, then choose your own password.

## Configuration

Settings come from a `.env` file in the app folder (see `.env.example`), overridden by environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `data` | Folder for the live `tasks.db`. Keep it out of synced folders. |
| `BACKUP_DIR` | `backups` | Where nightly backups go; point it at OneDrive / Google Drive |
| `LOG_DIR` | `logs` | Daily-rotated `app.log`, kept 14 days |
| `TIMEZONE` | `Asia/Kolkata` | Used for "today" and for showing times |
| `BACKUP_HOUR` | `23` | Hour of the nightly backup, in `TIMEZONE` |
| `BACKUP_KEEP` | `30` | Number of backups to keep |
| `BACKUPS_ENABLED` | `1` | Set to `0` to switch the nightly backup off |
