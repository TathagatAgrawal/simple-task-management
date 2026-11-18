# Design philosophy

The app has three users and no IT support, and it should keep working for years with only the occasional update. Every decision follows from that. When a choice is unclear, take the option with fewer moving parts.

## Principles

### 1. Boring, few dependencies

The runtime dependencies are FastAPI, Uvicorn, Jinja2, tzdata (Windows has no built-in timezone database) and pywebpush (it signs and encrypts the alerts that reach a phone when the board is closed; it brings `cryptography` and `requests` with it). That's all. The web client is one built file, `static/dist/app.js` (Preact, about 21 KB gzipped), committed to the repository and served by the app itself, not fetched from a CDN, so the app works even if a CDN is down or blocked.

There is no ORM, no CSS framework, no Docker and no separate database server. The client is written in TypeScript with Preact and built with Vite, so developers need Node, **but the firm's PC never does**: the built bundle is committed, and CI fails if it doesn't match the source. Each of these was weighed against the same question: does it add something to install, update or debug on a Windows PC nobody maintains? Build tools are acceptable because they stay on developers' machines; anything that runs on the PC isn't, unless the firm would feel its absence.

**Rule of thumb:** a new dependency needs a reason the firm would feel. "It would be nicer to write" isn't enough.

### 2. One page, one JSON API

The browser loads `/` once, and a small TypeScript client does the rest through the JSON API under `/api`. The server owns all the rules, the history and the wording (dates are labelled in IST on the server and sent ready-made); the client only shows what the API returns and sends what people change, so there is no second copy of the business logic to keep in sync. If something looks wrong, a refresh shows the truth.

The API is the only door: any other client (a phone app, a script) gets exactly what the web page gets, and its types are generated from the server's schema so the two cannot drift apart unnoticed. Pages stay current through one Server-Sent Events connection that says "something changed" (no polling load, no WebSockets), with a slow refresh as a safety net.

### 3. Plain SQL in one place

All SQL is in `store.py`, written as readable SQL strings with `?` parameters. Five tables don't need an ORM, and plain SQL is easy for anyone, including an AI agent, to read and check. Routes in `app.py` never touch SQL directly.

### 4. History is never lost

Every change to a task (status, assignees, due date, title, notes, repeat) writes an `event` row to that task's updates thread **in the same transaction** as the change. The thread is the complete, trustworthy history of a task, which matters for a firm doing compliance work. Never add a write path that changes a task without logging an event.

People are never hard-deleted. Removing someone sets `is_active = 0`, so their name stays on past comments.

### 5. Nobody gets blocked

There's no workflow enforcement. Any status can move to any other. Anyone can edit any task. There are only two roles: admin and not-admin. Three colleagues who trust each other don't need permissions. They need to see who did what, and the thread already shows that.

### 6. Correct dates, in the firm's timezone

Deadlines are the whole point of the app. "Today" is always computed in IST (`Asia/Kolkata`) from an injected clock, never from the server's local time. Date logic lives in pure functions (`dates.py`, `recurrence.py`) that take `today` or `due` as arguments, so it can be tested exhaustively.

### 7. Easy for a non-technical person to run

- One folder, one SQLite file, one command (`uv run simple-task-management serve`).
- Schema migrations run automatically at startup.
- Backups run themselves every night.
- The Windows scripts print plain-English instructions and errors.
- Error messages shown in the UI (`UserError`) are written for an accountant, not a developer: "Please pick a valid due date.", not "ValueError: invalid isoformat".

### 8. Desktop-first (for now)

The target is a desktop browser (Chrome or Edge, 1280px or wider). A mobile layout is planned for a later version, so don't make choices that block it, but don't spend effort on phones yet.

## Deliberately not built (v1)

Each of these is a reasonable feature, but none is needed yet. Don't add them without the user asking:

| Not built | Why |
|---|---|
| Roles and permissions beyond admin | Three trusted colleagues; the thread already shows who did what |
| Projects, labels, priorities, sub-tasks | The due date is the priority, and title text covers the rest |
| Manual card ordering within a column | Columns sort by due date, which is the order that matters for deadlines |
| File attachments | Files live in the firm's existing folders and email |
| Email | The bell and system alerts (Web Push, see [design/web-push.html](design/web-push.html)) cover it; email would add an outside service and credentials to look after |
| WebSockets | Server-Sent Events already push "something changed" to every open page; two-way sockets would add complexity nobody needs |
| Public internet access (Tailscale Funnel) | Task titles contain client names, so the app stays tailnet-only |
| Mobile layout | Planned next; see the design plan's "Later versions" |

## How to judge a new feature request

1. **Would the firm notice if it were missing?** If not, don't build it.
2. **Can it reuse what exists?** For example, a new task field should be a column on `tasks` plus a field in the task view, not a new subsystem.
3. **Does it add a dependency or a background process?** If so, look hard for a way that doesn't.
4. **Does it keep the history complete?** Any task mutation must write an event.
5. **Can it be tested without the real clock or network?**
6. **Is there one obvious place for it?** If it needs code in many files, the design is probably wrong.

## Code style in one breath

Small modules with one job each. Clear names over comments. A docstring on every module, function and test (including private helpers). Comments explain *why*, not *what*. Type hints on public functions. Ruff handles lint and formatting. Match the style of the surrounding code.
