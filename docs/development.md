# Development guide

## Setup

```bash
brew install uv          # or see https://docs.astral.sh/uv/
uv sync                  # creates .venv with Python 3.13 and all dependencies
```

Run the app against throwaway data. The `demo-*` folders are git-ignored.

```bash
export DATA_DIR=demo-data BACKUP_DIR=demo-backups LOG_DIR=demo-logs BACKUPS_ENABLED=0
uv run simple-task-management seed-demo        # asha (admin), ravi, meera
uv run simple-task-management serve --reload   # http://127.0.0.1:8000
```

## Commands

| Command | What it does |
|---|---|
| `uv run pytest` | Full test suite (~3s) |
| `uv run pytest tests/test_tasks.py -k recurring` | One area |
| `uv run ruff check .` | Lint, including docstring rules (Google convention) |
| `uv run ruff format .` | Format. CI runs `--check` |
| `uv add <pkg>` / `uv add --dev <pkg>` | Add a dependency, which updates `uv.lock`. Read [philosophy.md](philosophy.md) first |

CI (`.github/workflows/ci.yml`) runs lint and format on Ubuntu, the tests on Ubuntu, Windows and macOS, and parses plus PSScriptAnalyzer-checks every `deploy/windows/*.ps1`.

## Conventions

- **Docstrings everywhere:** every module, function, method, private helper and test. This is a project rule. Ruff enforces it for public names; do private ones by hand.
- **Layering:** routes in `app.py` call `store.*`. SQL lives only in `store.py` (plus the sessions queries in `auth.py`). Pure date logic lives in `dates.py` and `recurrence.py`. See [architecture.md](architecture.md).
- **User-facing errors:** raise `store.UserError("Plain-English sentence.")`. It becomes a `400` and shows in the banner. Don't leak exception text to users.
- **FastAPI parameters:** use `Annotated[..., Form()]` and the `Conn`, `User` and `Admin` aliases inside `create_app`. Don't use default-argument `Depends()`.
- **Two front doors, one store:** the HTML routes in `app.py` and the JSON routes in `api.py` both call `store.*`. A new business rule goes in `store.py`; add the JSON endpoint (and test) next to the HTML one when the feature should be reachable from both. See [architecture.md](architecture.md#the-json-api).
- **Mutating endpoints** return `Response(status_code=204, headers=TASKS_CHANGED)` (see the contract in [architecture.md](architecture.md#the-tasks-changed-contract)).
- **Transactions:** wrap each write in `with conn:`. Business-rule checks that read data go before it; writes and their events go inside it.
- **Time:** never call `date.today()` or `datetime.now()` in app logic. Take `today` as a parameter (store/dates) or use the `today()` closure (app). Tests use a fixed clock.
- **Templates:** fragments start with `_`. Keep logic minimal: pass ready-made values (labels, tones) from Python.
- **CSS:** use the variables on `:root` (`--surface`, `--accent`, ...). Never hard-code colours, so both themes keep working. Dark values are defined twice in `app.css` (the System media query and `[data-theme="dark"]`); change both.
- **JS:** only for things HTML and htmx can't do. Expose helpers as `window.tb*` and keep them in `board.js`.
- **Icons, not emoji:** use the `icon()` macro from `templates/_icons.html` (small line SVGs that take the text colour). Add new icons there.
- **Form errors:** give a form a `<p class="error form-error">` slot to show `400` messages next to its fields; otherwise they go to the banner.
- **Static files** are cache-busted with a hash of their contents (`static_fingerprint()`), computed at startup. The dev server's `--reload` only watches `.py` files, so restart it (or touch `app.py`) after editing CSS or JS.
- **Text:** ruff flags look-alike Unicode (e.g. en dashes, RUF001) in Python strings; use ASCII `-` in code. Typographic quotes in event messages are deliberate.

## Recipes

### Add a column to tasks

Example: an optional `client` field.

1. **Migration:** in `db.py`, append to `MIGRATIONS`:
   ```python
   MIGRATIONS: list[str] = [
       "ALTER TABLE tasks ADD COLUMN client TEXT NOT NULL DEFAULT '';",
   ]
   ```
   Leave `schema.sql` alone, since existing databases are already at version 1. Update `test_migrate_is_idempotent`'s expected version.
2. **Store:** accept the field in `create_task` and `update_task`, validate it with a `clean_*` helper, and log an event when it changes (e.g. `set the client to “Patel Traders”`).
3. **Route:** add `client: Annotated[str | None, Form()] = None` to `POST /tasks` and `POST /tasks/{id}`.
4. **Templates:** add an input to the New task dialog in `index.html` and to `_panel.html` (a field with its own `hx-post="/tasks/{id}" hx-trigger="change" hx-swap="none"`, in the main column or the sidebar), plus a chip in `_card.html` if it should show on cards.
5. **Tests:** creation, editing (exactly one event), and validation.
6. **Docs:** update the table in [data-model.md](data-model.md).

### Add a new mutating endpoint

1. Write a function in `store.py` that validates, writes inside `with conn:`, and writes an event.
2. Add the route in `app.py`: `User` dependency, `Form()` parameters, call the store, and return `204` + `TASKS_CHANGED`.
3. Trigger it from a template with `hx-post`, and set `hx-swap="none"` explicitly (because of inheritance).
4. Test the happy path and the error path through the HTTP client, which also covers CSRF.

### Add a new region to the page

Add an empty element to `index.html` with `hx-get` and `hx-trigger="load, tasks-changed from:body"`, add a `GET` route that renders a new `_fragment.html`, and you're done: it stays in sync with no JS.

### Update the user manual

The manual is `templates/help.html`, with screenshots in `static/help/*.jpg`. Annotations aren't baked into the images. Each `figure()` call lists numbered **pins**, highlight **boxes** and **arrows** in the screenshot's own pixel coordinates, and the template converts them to percentages, so they stay aligned at any page width. `tests/test_help.py` checks that every referenced image exists.

When the UI changes in a way that makes a screenshot wrong:

1. Run the app on fresh demo data (`seed-demo`) and set the theme to **Light** (screenshots are all light).
2. Use a ~1280px-wide browser window and move the mouse pointer out of the shot.
3. Capture the screen or just the relevant area. Crops are taken at 2× for sharpness.
4. Save it as JPEG (quality ~80) over the old file in `static/help/`, keeping the name. On a Mac: `sips -s format jpeg -s formatOptions 82 shot.png --out static/help/board.jpg`.
5. If the image size changed, update the `w`/`h` arguments of its `figure()` call. If things moved, update the pin, box and arrow coordinates (read them off the image in any image viewer), and check the page in a browser.
6. Update the text if the behaviour changed.

### Change what the "coming up" strip includes

Edit `dates.bucket` and `SOON_DAYS`, plus the SQL horizon in `store.summary`, then update `test_dates.py` and `test_summary.py`.

## Testing

- `tests/conftest.py` provides `settings` (temp dirs, backups off), `conn` (migrated), `users` (asha admin, ravi, meera), `app` (fixed clock: **Sat 14 Nov 2026, 10:00 IST**), and signed-in clients `asha` and `ravi`.
- `sign_in(app, username, password)` performs the real login flow, scrapes the CSRF token from the page, and sets the `X-CSRF-Token` and `HX-Request` headers like htmx would.
- `new_task(client, **fields)` creates a task through HTTP and asserts `204`.
- Prefer HTTP-level tests (they cover routing, auth, CSRF and the store together). Use direct `store.*` calls for setup or for logic that's awkward over HTTP.
- Date logic uses parametrised tables with explicit dates: month-ends, leap years, year boundaries.
- `tests/test_api.py` has `api_client(app, username)`, which signs in through `POST /api/session` and sends the bearer token. `tests/test_mobile.py` checks the phone markup and the manifest and icons.
- The JS isn't unit-tested. After changing `board.js` or templates, click through the checklist in the root README ("A pre-shipping checklist") in a real browser.

## Gotchas

| Symptom | Cause / fix |
|---|---|
| An htmx request sends unexpected params, or swaps the wrong element | Inherited `hx-include`, `hx-target` or `hx-swap` from an ancestor. Set them explicitly |
| `403 Your session changed` | A POST without `X-CSRF-Token`. Requests must originate inside `<body hx-headers=...>`, or pass the header in tests |
| `ProgrammingError: SQLite objects created in a thread...` | FastAPI may run a dependency and its route on different threads. `db.connect()` sets `check_same_thread=False`; always use it |
| Works on Mac, fails on Windows | Platform-specific `strftime` flags (`%-d`), path separators, or a missing `tzdata` |
| The board doesn't refresh after an action | The endpoint didn't send `HX-Trigger: tasks-changed`, or the request returned non-2xx |
| Card snaps back after a drop | The move failed; the banner shows why. This is intended |
