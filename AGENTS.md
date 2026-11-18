# Agent instructions

Start with [docs/README.md](docs/README.md). It explains what this app is, the design philosophy (clean and simple, few dependencies, server-rendered single page), the reading order of the other docs, and the checks to run before opening a pull request.

Essentials, in case you read nothing else:

- Keep it simple. Don't add dependencies, build steps, background services or abstractions unless the user asks; see [docs/philosophy.md](docs/philosophy.md).
- SQL lives only in `store.py`; routes in `app.py` call it. Every task change must write an `event` row in the same transaction.
- There is one responsive page (a `max-width: 640px` block in `app.css` plus the phone section of `board.js`), and a JSON API in `api.py` under `/api` that calls the same `store.*` functions. A new rule goes in `store.py`; keep the HTML and JSON routes in step.
- Mutating endpoints return `204` with `HX-Trigger: tasks-changed`; the page regions refresh themselves.
- Never use `date.today()`/`datetime.now()` in app logic; "today" is computed in IST from the injected clock.
- Every module, function and test gets a docstring, including private helpers.
- Before finishing: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`.
- Update the matching file in `docs/` when you change structure, tables or conventions.
