# Start here

This is the developer and agent guide for **Simple Task Management**, a one-page task board for a three-person Chartered Accountant (CA) firm. If you're new to the codebase, human or AI, read this page first, then follow the reading order below. You should not need anyone to re-explain the project after that.

## The app in one paragraph

Three people share a board of tasks. Each task has a title, notes, one or more assignees, a due date, an optional repeat schedule and a thread of updates. The board has three columns (To do, Doing, Done) and cards move between them by drag-and-drop. A strip across the top shows what's overdue, due today and due in the next three days. One flag, `is_admin`, lets someone add and remove people. The app runs on one always-on Windows 10 PC in the office, and staff open it in a desktop browser over Tailscale. It has to keep running for years with nobody technical looking after it.

## The one rule

**Keep it clean and simple.** The firm has three users and no IT person. Every dependency, abstraction, build step or moving part is something that can break on a PC nobody maintains. Before adding anything, ask whether the firm would notice it was missing. [philosophy.md](philosophy.md) explains this in detail, and it's the most important doc here.

## Reading order

| # | Doc | Read it to learn |
|---|---|---|
| 1 | [philosophy.md](philosophy.md) | The design principles, what we deliberately don't build, and how to judge a new feature |
| 2 | [architecture.md](architecture.md) | How a request flows, the "one page + htmx fragments" pattern, and what each module owns |
| 3 | [data-model.md](data-model.md) | The five tables, their invariants, recurring tasks, history events, dates and timezones, migrations |
| 4 | [development.md](development.md) | Setup, commands, code conventions, step-by-step recipes for common changes, testing, and known gotchas |
| 5 | [operations.md](operations.md) | How it's deployed and run on Windows, the security model, backups and recovery |
| – | [design/plan.html](design/plan.html) | The original design plan with diagrams and UI mockups. It's the historical record of *why*; where it differs from the code, the code and these docs win. |

The root [README.md](../README.md) is the user-facing guide: how to try the app on a Mac, deploy it on Windows, and what staff need to do.

## Where things are

```
src/simple_task_management/
  app.py          routes: the one page + HTML fragments          (HTTP layer, no SQL)
  store.py        all SQL for tasks, assignees, updates, people   (data + business rules)
  recurrence.py   next-due-date arithmetic                        (pure functions)
  dates.py        "today" in IST, buckets, labels                 (pure functions)
  auth.py         password hashing, sessions, login throttle
  backup.py       online SQLite backups + nightly loop
  config.py       settings from .env / environment
  db.py           connection pragmas + migrations
  schema.sql      the schema (version 1)
  __init__.py     CLI: serve, create-admin, set-password, backup, seed-demo
  templates/      index.html (the page) + _fragments.html (swapped in by htmx) + _icons.html
  static/         app.css (light/dark), board.js (~220 lines), htmx.min.js (vendored)
tests/            pytest; one file per area; fixed clock in conftest.py
deploy/windows/   PowerShell scripts for install, status, restart, update
docs/             you are here
```

## Quick commands

```bash
uv sync                                              # install
uv run pytest                                        # 64 tests, ~4 seconds
uv run ruff check . && uv run ruff format .          # lint + format (CI enforces both)
DATA_DIR=demo-data uv run simple-task-management seed-demo
DATA_DIR=demo-data uv run simple-task-management serve --reload
```

## Before you open a pull request

- `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` all pass. CI runs the tests on Ubuntu, Windows and macOS, and checks the PowerShell scripts.
- Every module, function and test has a docstring. This includes private helpers.
- New behaviour has a test. Date logic is tested with explicit dates, never the real clock.
- If you changed the structure, a table, or a convention, update the matching doc here in the same change.
