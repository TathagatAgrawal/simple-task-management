# Architecture

## The big picture

```
 Staff browser ──WireGuard──▶ Tailscale Serve (HTTPS) ──▶ Uvicorn :8000 (127.0.0.1 only)
                                                              │
                                                    FastAPI app (app.py)
                                                              │
                                     store.py ── db.py ── SQLite file (data/tasks.db)
                                         │
                              dates.py, recurrence.py, auth.py
                                                              │
                                     backup.py (nightly, inside the app) ──▶ BACKUP_DIR
```

The app is a single Python process. It listens only on localhost, and Tailscale Serve is the only way in. There are no other services.

## Module responsibilities and dependency direction

Dependencies point one way. Lower layers never import higher ones.

```
__init__.py (CLI) ─┐
                   ├─▶ app.py ─▶ api.py ─▶ store.py ─▶ db.py
                   │      │         │──────▶ dates.py, recurrence.py (pure, no I/O)
                   │      │         └──────▶ auth.py (hashing, temp passwords)
                   │      └─▶ auth.py, dates.py, backup.py, config.py
                   └─▶ backup.py, store.py, config.py
```

| Module | Owns | Must not |
|---|---|---|
| `app.py` | Routes, dependencies (DB connection, current user, admin check, CSRF), error handling, template rendering | Contain SQL or business rules |
| `api.py` | The JSON API (`/api/...`): request/response shapes, bearer-or-cookie auth, JSON errors. A sub-app that `create_app` mounts, so its error handling and OpenAPI schema are separate from the HTML app's | Contain SQL or business rules (call `store.*`), render HTML |
| `store.py` | All SQL; validation (`clean_title`, `parse_due`, ...); business rules (events, recurrence spawning, admin safety rails) | Know about HTTP, requests or templates |
| `dates.py` | The firm's "today", summary buckets, display labels | Read the clock (it takes `now`/`today` as arguments) |
| `recurrence.py` | `next_due()` and month arithmetic | Touch the database |
| `auth.py` | scrypt hashing, sessions table access, temp passwords, login throttle | Know about routes |
| `db.py` | `connect()` (pragmas), `migrate()`, `now_iso()` | Contain queries for app data |
| `config.py` | `Settings` from `.env` and environment | Have side effects |
| `backup.py` | Online backup, pruning, the nightly asyncio loop | – |
| `__init__.py` | CLI sub-commands and logging setup | Contain logic that the web app also needs (put it in `store.py`) |

`create_app(settings, clock)` in `app.py` is a factory. Routes are defined inside it as closures, so each app instance (and each test) gets its own settings, clock, templates and login throttle without any global state.

## The one-page pattern

`GET /` returns `templates/index.html` in one of three states:

1. **Signed out:** the login form.
2. **Must change password:** the "choose your own password" form, shown after an admin creates or resets an account.
3. **Signed in:** the app shell. This is a top bar, empty `#summary` and `#board` regions, the task drawer (a `<dialog id="task-dialog">` holding an empty `#panel`), and three more `<dialog>`s (New task, Change password, and People for admins).

The regions fill themselves with htmx:

```html
<section id="board" hx-get="/board" hx-include="#who, #done-days"
         hx-trigger="load, filters-changed from:body, tasks-changed from:body,
                     every 60s [!tbDragging], focus from:window">
```

### The `tasks-changed` contract

This is the core idea. Learn it before changing any route.

- **Every endpoint that changes a task** returns `204 No Content` with the header `HX-Trigger: tasks-changed`. It does not return HTML.
- htmx fires a `tasks-changed` event, which bubbles to `<body>`.
- `#summary`, `#board` and the open task view all listen for `tasks-changed from:body` and re-fetch themselves.

As a result, no endpoint needs to know which parts of the page to update, and adding a new kind of change needs no client-side wiring. The cost is a couple of small extra GETs, which is irrelevant at this scale.

Exceptions:

- **People endpoints** return the re-rendered `_people.html` fragment, because the dialog shows a one-time temporary password. They send `HX-Trigger: people-changed`, and `board.js` reloads the page when the dialog closes so the filter and assignee lists pick up the new people.
- **Login, logout and the forced password change** answer with `HX-Redirect: /`.
- **Validation errors** raise `store.UserError`, which becomes `400` with a plain-text message. `board.js` shows it in the red `#banner` and fires `tasks-changed` to re-sync, which also snaps back a card whose drag failed.
- **401** answers htmx requests with `HX-Redirect: /` and normal requests with a `303` redirect to `/`.

### Fragments

| Route | Template | Notes |
|---|---|---|
| `GET /summary?who=` | `_summary.html` | Overdue / today / next 3 days. Each task is a clickable row; groups show 3 rows and hide the rest behind "Show N more" |
| `GET /board?who=&done_days=` | `_board.html` + `_card.html` | Done shows the last 14 days by default |
| `GET /tasks/{id}` | `_panel.html` | The task view. Returns an **empty body** if the task was deleted, which closes the drawer |
| `GET /people` and the `POST /people...` routes | `_people.html` | Admin only |
| `GET /help` | `help.html` | The user manual: a separate full page (linked from the top bar and login screen, opens in a new tab). Readable without signing in; uses the person's theme if they are. Screenshots live in `static/help/` |

`who` is `me`, `all`, `none` (unassigned) or a user id. Unknown values fall back to `me`.

### The task drawer

Clicking a card or a summary item loads `_panel.html` into `#panel`, and `board.js` then opens the drawer: a modal `<dialog>` that slides in from the right *over* the board (like GitHub's project item view), so the columns never change width. It has the title in a header, and notes, the updates thread and the comment box in the main column. The drawer has a fixed height: only the thread (`.thread-scroll`) scrolls, so the comment box is always visible at the bottom. The thread opens scrolled to the newest update, and keeps your position across refreshes if you've scrolled up. Status, assignees, due date, repeat and delete are in a right sidebar. Clicking outside, ✕, or Esc closes it. Esc first leaves a text field, which saves it, and only a second Esc closes the drawer.

`_panel.html`'s root element re-fetches itself (`hx-swap="outerHTML"`) on `tasks-changed`, and every 60 seconds when `tbPanelIdle()` reports that nobody is typing in it. Because it re-renders after every change, `board.js` carries over what the server doesn't know: an unsent comment, which field had keyboard focus (found again by `name`), and expanded `<details>`. Title, notes, due date and repeat each post themselves on `change` (`hx-post` on the field, outside any form, so only that field is sent). The assignee chips are one small form, and the status control is a set of buttons.

**htmx inheritance gotcha:** children inherit `hx-target`, `hx-swap` and `hx-include` from their ancestors. That's why every form, field and button in the task view sets `hx-swap="none"` explicitly, and why cards on the board send `who` and `done_days` query parameters. The server ignores the extra parameters.

## The phone layout

There is one page, not a separate mobile site. `app.css` has one `@media (max-width: 640px)` block that restyles the same templates, and `board.js` adds the touch behaviour. Everything mobile-only is hidden on larger screens.

| Desktop | Phone |
|---|---|
| Top bar with Help and the user menu | Compact bar: title, the "Showing" select as a pill, a round **+**. Help and the user menu become the **Me** tab (`#me-view` in `index.html`) |
| Summary strip above the board | The **Coming up** tab. The overdue count is read from `data-overdue` on `.summary` into a badge on the tab |
| Three columns | One column at a time, chosen with the segmented control (`.col-tabs`, rendered inside `_board.html` so its counts refresh with the board). The tab and status are `data-tab` / `data-seg` on `<body>` and are remembered in `localStorage` |
| Drag-and-drop | Swipe a card right to move it on (To do → Doing → Done → To do), swipe left or press and hold for the `#card-actions` sheet (Open, Move to, Delete). Each card sits in a `.card-wrap` so a coloured hint shows behind it as it slides |
| Task drawer on the right | The `<dialog>` becomes a full-screen page that slides in from the right. `.panel-body` is the one scroller and the composer is `position: sticky` at the bottom. Opening a task pushes a history entry, so the phone's Back button or back gesture closes it; the ‹ button and a swipe right from the left edge do the same |
| Modal dialogs | Bottom sheets (drag the grab handle down, or tap the dimmed area, to dismiss) |

The on-screen keyboard is handled with `window.visualViewport`: `board.js` sets `--kb` (the keyboard's height) while a field is focused, and the CSS lifts sheets and the task page above it. Inputs are 16 px so iOS doesn't zoom. Safe-area insets keep the tab bar clear of the home indicator.

### Installing it on a phone

`index.html` links `/manifest.webmanifest` (served by `app.py` from `static/manifest.webmanifest`, `display: standalone`) and sets the Apple meta tags, so "Add to Home Screen" gives an icon that opens the app without browser chrome. Icons are in `static/icons/` (`icon.svg` is the source; the PNGs are full-bleed squares because iOS and Android apply their own rounding). There is deliberately **no service worker**: Chrome no longer needs one to install, and the app doesn't work offline. The installed app on iOS has its own cookie storage, so each person signs in once more inside it.

## The JSON API

`/api` is a second interface to the same data, for any client that would rather not parse HTML fragments (another front end, a phone app, a script). It is additive: the htmx UI keeps using the HTML fragment routes above, and both call the same `store.*` functions, so rules and history events can't drift apart. The schema is published at `/api/openapi.json`.

| Area | Endpoints |
|---|---|
| Session | `POST /api/session` (returns a bearer `token`), `DELETE /api/session` |
| Me | `GET /api/me`, `PATCH /api/me` (theme), `POST /api/me/password` |
| Board | `GET /api/board?who=&done_days=`, `GET /api/summary?who=` |
| Tasks | `POST /api/tasks`, `GET`, `PATCH` and `DELETE /api/tasks/{id}`, `POST /api/tasks/{id}/updates` |
| People | `GET /api/people`, and for admins `POST /api/people`, `PATCH /api/people/{id}`, `POST /api/people/{id}/reset-password`, `DELETE /api/people/{id}` |

Conventions: JSON in, JSON out; errors are always `{"error": "message"}` with `400` (our rules), `401`, `403`, `404` or `422` (missing or unknown fields); unknown request fields are rejected. Send `Authorization: Bearer <token>`. The browser session cookie works too, but then unsafe requests need the `X-CSRF-Token` header (from `GET /api/me`); bearer requests need no CSRF header. `PATCH /api/tasks/{id}` takes any subset of title, notes, due, repeat, status and assignee_ids, validates all of them before applying any, and returns `next_task_id` when finishing a recurring task created the next occurrence. A person who still has a temporary password can only call `POST /api/me/password`.

## What `board.js` does (and only this)

| Area | Behaviour |
|---|---|
| Errors | Shows `400` text inside the form when it has a `.form-error` slot (dialogs, set-password), otherwise in the `#banner` popover, which sits in the top layer so it shows above open dialogs. Also generic `5xx` text, and "Can't reach the server" on network errors |
| Filter | Remembers the "Showing" choice in `localStorage` and fires `filters-changed` |
| Summary | `tbToggleSummary()` expands a group's hidden rows, and re-applies that after the strip's background refreshes |
| Task drawer | Opens it when a task loads into `#panel` (and after creating a task, via the `task-created` trigger), closes it on backdrop click / Esc / deletion, keeps `#task-N` in the URL, highlights the selected card, opens the task in the URL hash on load, and preserves draft, focus, expanded sections and thread scroll position across refreshes |
| Drag-and-drop | Native HTML5 API. On drop it moves the card optimistically and calls `htmx.ajax("POST", "/tasks/N/move", ...)`; polling pauses while dragging (`window.tbDragging`) |
| Dialogs | `tbOpenDialog(id)`; reloads the page after the People dialog closes if anything changed |
| Phone layout | Tabs and the status control (`tbSetTab`, `tbSetSeg`), the overdue badge, swipe and press-and-hold on cards, the card actions sheet, edge-swipe and drag-down dismissal, history entries for the open task, and the keyboard height (`--kb`). Touch only (`pointerType !== "mouse"`), and only under 640 px |
| Theme | `tbSetTheme()` flips `data-theme` on `<html>` immediately. The server persists it via `POST /me/theme` |

## Security model (summary)

- **Network:** the app listens only on localhost, and Tailscale Serve handles HTTPS. Everyone at the firm shares one Tailscale login, so Tailscale can't tell people apart. That's why the app has its own accounts.
- **Sessions:** a random 32-byte token in an `HttpOnly`, `SameSite=Lax` cookie (with `Secure` when the request is HTTPS), stored in the `sessions` table with a 30-day expiry.
- **CSRF:** each session has its own `csrf_token`. `index.html` puts it in `hx-headers` on `<body>`, so every htmx request sends `X-CSRF-Token`, and `require_user` checks it on every POST. `/login` requires the `HX-Request` header instead, because a cross-site form can't set custom headers.
- **Passwords:** stdlib `hashlib.scrypt` with a per-user salt. Repeated failed logins for the same username are slowed down (`LoginThrottle`).
- **Output escaping:** Jinja autoescapes everything. Where we build `Markup` by hand (the `link_tasks` filter and the people flash messages), we escape user text first. Keep it that way.

More detail is in [operations.md](operations.md).
