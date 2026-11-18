# Development guide

## Setup

```bash
brew install uv          # or see https://docs.astral.sh/uv/
uv sync                  # creates .venv with Python 3.13 and all dependencies
brew install node        # only to work on the web client (web/); the app itself never needs Node
npm --prefix web ci      # installs the client's build tools into web/node_modules
```

Run the app against throwaway data. The `demo-*` folders are git-ignored.

```bash
export DATA_DIR=demo-data BACKUP_DIR=demo-backups LOG_DIR=demo-logs BACKUPS_ENABLED=0
uv run simple-task-management seed-demo        # asha (admin), ravi, meera
uv run simple-task-management serve --reload   # http://127.0.0.1:8000
```

To change the web client, keep a second terminal running `npm --prefix web run dev`. It rebuilds `static/dist/app.js` whenever you save a file in `web/src`; reload the page to see the change. Python changes reload by themselves.

## Commands

| Command | What it does |
|---|---|
| `uv run pytest` | Full test suite (~3s) |
| `uv run pytest tests/test_tasks.py -k recurring` | One area |
| `uv run ruff check .` | Lint, including docstring rules (Google convention) |
| `uv run ruff format .` | Format. CI runs `--check` |
| `npm --prefix web run build` | Type-check the client and write `static/dist/app.js`. **Commit the result** |
| `npm --prefix web run types` | Regenerate `web/src/api/schema.d.ts` from the API. Run after changing any API route or `schemas.py`, and commit it |
| `npm --prefix web test` | The client's unit tests (vitest) |
| `npm --prefix web run typecheck` | Type-check only |
| `uv add <pkg>` / `uv add --dev <pkg>` | Add a dependency, which updates `uv.lock`. Read [philosophy.md](philosophy.md) first |

CI (`.github/workflows/ci.yml`) runs lint and format on Ubuntu, the tests on Ubuntu, Windows and macOS, type-checks and tests the web client and fails if the committed `schema.d.ts` or `static/dist/app.js` differ from a fresh build, and parses plus PSScriptAnalyzer-checks every `deploy/windows/*.ps1`.

## Conventions

- **Docstrings everywhere:** every module, function, method, private helper and test. This is a project rule. Ruff enforces it for public names; do private ones by hand.
- **Layering:** routes in `api.py` call `store.*`. SQL lives only in `store.py` (plus the sessions queries in `auth.py`). Pure date logic lives in `dates.py` and `recurrence.py`. See [architecture.md](architecture.md).
- **User-facing errors:** raise `store.UserError("Plain-English sentence.")`. It becomes a `400` and shows in the banner. Don't leak exception text to users.
- **FastAPI parameters:** use the `Conn`, `User` and `Admin` aliases inside `build_api`, and a request model (in `api.py`) for bodies. Don't use default-argument `Depends()`.
- **One door, one store:** the client talks only to the JSON API, and every route calls `store.*`. A new business rule goes in `store.py`. See [architecture.md](architecture.md#the-json-api).
- **Every API response has a model** in `schemas.py` and the route says `response_model=...`. That's what makes the client's generated types exact. Return plain dicts that fit the model.
- **Announce changes:** a route that changes data calls `changed("tasks", ...)` (topics: `tasks`, `notifications`, `people`) after the store call, so every open page refreshes at once. See "Live updates" in [architecture.md](architecture.md#live-updates).
- **Transactions:** wrap each write in `with conn:`. Business-rule checks that read data go before it; writes and their events go inside it.
- **Time:** never call `date.today()` or `datetime.now()` in app logic. Take `today` as a parameter (store/dates) or use the `today()` closure (app). Tests use a fixed clock.
- **Ready-made values:** the client contains no date or wording logic. Compute labels, tones and "when" strings in Python and send them in the response.
- **CSS:** use the variables on `:root` (`--surface`, `--accent`, ...). Never hard-code colours, so both themes keep working. Dark values are defined twice in `app.css` (the System media query and `[data-theme="dark"]`); change both.
- **Client code:** TypeScript in `web/src`, strict mode. Shared state and everything that changes it live in `state.ts`; components only read signals and call those functions. Keep the existing class names so `app.css` keeps working. Never render a person's text as HTML.
- **Icons, not emoji:** use the `Icon` component (`web/src/components/Icon.tsx`, small line SVGs that take the text colour). Add new icons there.
- **Form errors:** show `400` messages next to the form's fields (a `<p class="error form-error">`), or in the banner with `fail(error)` from `state.ts`.
- **Static files** are cache-busted with a hash of their contents (`static_fingerprint()`), computed at startup. The dev server's `--reload` only watches `.py` files, so restart it (or touch `app.py`) after editing CSS.
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
3. **API:** add `client` to the `TaskIn` and `TaskPatch` models and to `task_json` and `schemas.Task` (and to the card, if it should show on the board). Run `npm --prefix web run types`.
4. **Client:** add an input to `NewTaskForm` in `Dialogs.tsx` and a field to `Panel` in `TaskDrawer.tsx` (a small component like `Notes` that saves with `saveTask(id, { client })`), plus a chip in `CardView` in `Board.tsx` if it should show on cards. Run `npm --prefix web run build` and commit the bundle.
5. **Tests:** creation, editing (exactly one event), and validation.
6. **Docs:** update the table in [data-model.md](data-model.md).

### Add a new mutating endpoint

1. Write a function in `store.py` that validates, writes inside `with conn:`, and writes an event.
2. Add the route in `api.py`: `User` dependency, a request model, call the store, call `changed(...)` with the topics it affects, and give it a `response_model` (in `schemas.py`).
3. Run `npm --prefix web run types`, add a function to `api/client.ts` and an action to `state.ts`, and call it from a component.
4. Test the happy path and the error path through the HTTP client, which also covers CSRF, and that `changed` announces the right topics (see `tests/test_events.py`).

### Add a new region to the page

Add a component, read its data from a signal in `state.ts`, load it with a `refresh*` function, and call that function from the right topic in `onTopics` (`live.ts`) so it stays current by itself.

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
- `sign_in(app, username, password)` signs in through `POST /api/session` like the page does, and sets the `X-CSRF-Token` header. Helpers `new_task`, `move`, `board` and `board_titles` wrap the common API calls.
- Prefer HTTP-level tests (they cover routing, auth, CSRF and the store together). Use direct `store.*` calls for setup or for logic that's awkward over HTTP.
- Date logic uses parametrised tables with explicit dates: month-ends, leap years, year boundaries.
- `tests/test_api.py` has `api_client(app, username)`, which signs in through `POST /api/session` and sends the bearer token. `tests/test_mobile.py` checks the shell, the manifest, the icons and that the built bundle is shipped. `tests/test_events.py` covers the live-update hub and what each change announces.
- The client has unit tests for its pure helpers (`web/src/*.test.ts`, run with `npm --prefix web test`). Screens, drag-and-drop and gestures are checked by hand: after changing the client, build it and click through the checklist in the root README ("A pre-shipping checklist") in a real browser, on a desktop-width window and a phone-width one.

## Gotchas

| Symptom | Cause / fix |
|---|---|
| A type error after changing the API | Expected: `web/src/api/schema.d.ts` is regenerated by `npm --prefix web run types`, and the compiler lists every place in the client that needs to follow |
| `403 Your session changed` or `Missing or wrong X-CSRF-Token` | A write without the `X-CSRF-Token` header. The client sets it from `GET /api/me`; in tests use `sign_in` |
| `ProgrammingError: SQLite objects created in a thread...` | FastAPI may run a dependency and its route on different threads. `db.connect()` sets `check_same_thread=False`; always use it |
| Works on Mac, fails on Windows | Platform-specific `strftime` flags (`%-d`), path separators, or a missing `tzdata` |
| Other people's pages don't refresh after an action | The route didn't call `changed(...)` for the right topics, or the request returned non-2xx |
| The page shows old behaviour after you edited the client | You edited `web/src` but didn't rebuild: run `npm --prefix web run build` (or keep `npm --prefix web run dev` running) and commit `static/dist/app.js` |
| CI says the committed bundle or types are out of date | Run `npm --prefix web run types` and `npm --prefix web run build`, then commit what changed |
| Card snaps back after a drop | The move failed; the banner shows why. This is intended |
