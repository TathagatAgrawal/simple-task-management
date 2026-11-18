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
| `app.py` | The page shell, `/help`, the manifest, `/sw.js`, `/healthz`, the static files, and mounting the API | Contain SQL or business rules, render task data |
| `api.py` | The JSON API (`/api/...`): request shapes, bearer-or-cookie auth, JSON errors, and announcing changes to the event hub. A sub-app that `create_app` mounts, so its error handling and OpenAPI schema are its own | Contain SQL or business rules (call `store.*`), render HTML |
| `schemas.py` | The response models that make the OpenAPI schema (and so the client's generated types) exact | Contain logic |
| `push.py` | Web Push: the signing key, the background sender that pushes new notifications after they are saved, the test alert | Be called inside a task's transaction (a push problem must never lose a change) |
| `events.py` | The live-update hub and the Server-Sent Events stream | Know what the topics mean to the client |
| `store.py` | All SQL; validation (`clean_title`, `parse_due`, ...); business rules (events, recurrence spawning, admin safety rails) | Know about HTTP, requests or templates |
| `dates.py` | The firm's "today", summary buckets, display labels | Read the clock (it takes `now`/`today` as arguments) |
| `recurrence.py` | `next_due()` and month arithmetic | Touch the database |
| `auth.py` | scrypt hashing, sessions table access, temp passwords, login throttle | Know about routes |
| `db.py` | `connect()` (pragmas), `migrate()`, `now_iso()` | Contain queries for app data |
| `config.py` | `Settings` from `.env` and environment | Have side effects |
| `backup.py` | Online backup, pruning, the nightly asyncio loop | – |
| `__init__.py` | CLI sub-commands and logging setup | Contain logic that the web app also needs (put it in `store.py`) |

`create_app(settings, clock)` in `app.py` is a factory. Routes are defined inside it as closures, so each app instance (and each test) gets its own settings, clock, templates and login throttle without any global state.

## The web client

`GET /` returns a tiny HTML shell (`templates/index.html`): the head tags, an empty `<div id="root">`, and a script tag for `static/dist/app.js`. Everything you see after that is a single-page client written in TypeScript with Preact, which talks to the server only through the JSON API under `/api` (see below). The server renders no task data as HTML. The one other server-rendered page is the user manual (`GET /help`, `help.html`): a static page linked from the top bar, the Me tab and the sign-in screen, readable without signing in and using the person's theme if they are. Its screenshots live in `static/help/`.

### Where the code lives

```
web/                        the client's source (needs Node to build; the app does not)
  package.json              scripts: types, build, dev, typecheck, test
  vite.config.ts            builds src/main.tsx into ../src/simple_task_management/static/dist/app.js
  scripts/export_openapi.py prints the API's OpenAPI schema (used by `npm run types`)
  src/api/schema.d.ts       GENERATED from the schema; never edit by hand
  src/api/types.ts          short names for the generated types
  src/api/client.ts         one typed function per endpoint, CSRF header, error messages
  src/state.ts              the shared state (signals) and every action that changes it
  src/live.ts               the live-update connection (below)
  src/alerts.ts             on-page messages, desktop alerts, and turning on push for this device
  src/gestures.ts           phone swipe, press-and-hold, sheet dismissal, keyboard height
  src/components/*.tsx      one file per area: Board, TaskDrawer, Notifications, Dialogs, Chrome, Auth, Modal
```

The built `static/dist/app.js` is **committed**, like the old vendored htmx file was, so the Windows PC runs the app with `git pull` and `uv` only; Node is for development. CI rebuilds the bundle and fails if the committed copy differs, so it can't go stale. `app.css` is unchanged and still styles everything: the components use the same class names the old templates did.

### How data flows

- `state.ts` holds signals (`board`, `summary`, `task`, `notifications`, `me`, `people` and so on). Components read them and re-render by themselves; there is no other client state to keep in sync.
- Loading functions (`refreshBoard`, `refreshTask`, `refreshNotifications`, ...) fetch from the API and set the signals. Overlapping calls collapse, and the board waits while a card is being dragged or swiped.
- Saving functions (`moveTask`, `saveTask`, `postUpdate`, ...) call the API, and the server's answer replaces the local copy. Moving a card updates the board first, then confirms with the server. A failed request shows its message in the red `#banner` and reloads the real state.
- Every API error is `{"error": "message"}`; `client.ts` turns it into an `ApiError` whose message is already written for an accountant. A `401` makes the client show the sign-in form.
- Date labels ("2 days late", "Tomorrow") are computed on the server in IST and sent ready-made, so the client contains no date logic.

### Live updates

Pages hold one **Server-Sent Events** connection, `GET /api/events` (`events.py`). When a request changes data, the API route calls `hub.publish("tasks", ...)`, and every connected page gets `data: ["tasks", "notifications"]` within a moment and refetches what it shows for those topics (`tasks` → board, summary and the open task; `notifications` → the bell and list; `people` → the people lists). The first message on a new connection is `["ready"]`, which makes the page refetch everything, so a page that was disconnected catches up. Nothing is stored or replayed.

- It is not WebSockets (one-way push is all that's needed) and not webhooks (a browser can't receive those).
- The hub lives in the one app process; `publish` is safe to call from the request threads. Several quick changes are merged into one message, and a `: ping` comment every 25 seconds keeps proxies from closing a quiet connection.
- Safety net: if the connection drops, the browser reconnects by itself, and the client also refetches everything every 60 seconds and whenever the window regains focus or becomes visible.
- At shutdown `hub.close()` ends the streams, and `uvicorn.run(..., timeout_graceful_shutdown=3)` stops open connections from delaying a restart.
- Tailscale Serve proxies the stream; if it were ever buffered, the 60-second refresh would still keep pages current.

### Search, shortcuts and the drawer's feedback

The search box filters the board and the strip by title in the browser (`matches` in `Board.tsx`); while it is in use the board loads older Done tasks too, so history is searchable. `n` opens New task and `/` focuses the search. A focused card moves with `[` and `]`; it keeps keyboard focus in its new column and a screen-reader message says where it went. The strip adds an "N more overdue across the firm" link when "Showing" hides other people's overdue work (`firm_overdue` in `GET /api/summary`).

Saving shows its state (`saveStatus` in `state.ts`): "Saving…" and "Saved ✓" in the drawer's header, and a failure puts the server's reason under the field that failed (`fieldErrors`) instead of in the banner. The red banner now stays until dismissed or until the next change succeeds. A due date in the past asks for confirmation first.

### The task drawer

Clicking a card or a summary item sets `openTaskId`, loads the task, and opens a modal `<dialog>` that slides in from the right *over* the board (like GitHub's project item view), so the columns never change width. It has the title in a header, and notes, the updates thread and the comment box in the main column. The drawer has a fixed height: only the thread scrolls, so the comment box is always visible at the bottom. The thread opens scrolled to the newest update, and stays where you left it if you've scrolled up. Status, assignees, due date, repeat and delete are in a right sidebar. Clicking outside, ✕, or Esc closes it. Esc first leaves a text field, which saves it, and only a second Esc closes the drawer.

Each field keeps its own draft and saves itself when you leave it (title, notes, due date, repeat) or click it (assignees, status). A field follows the server's copy except while you are editing it, so a background refresh never overwrites what you are typing, and an unsent comment survives refreshes because the component is never recreated. The URL hash is `#task-N` while a task is open, and opening a link with one loads that task.

## The phone layout

There is one page, not a separate mobile site. `app.css` has one `@media (max-width: 640px)` block that restyles the same markup, and `gestures.ts` adds the touch behaviour. Everything mobile-only is hidden on larger screens.

| Desktop | Phone |
|---|---|
| Top bar with Help, the bell and the user menu | Compact bar: title, the "Showing" select as a pill, a round **+**. Help, settings and sign out live in the **Me** tab (`MeView`) |
| Summary strip above the board | The **Coming up** tab, with the overdue count as a badge |
| The bell and its panel | The **Alerts** tab, with the unread count as a badge |
| Three columns | One column at a time, chosen with the segmented control (`.col-tabs`). The tab and status are `data-tab` / `data-seg` on `<body>`, set from `state.ts` and remembered in `localStorage` |
| Drag-and-drop | Swipe a card right to move it on (To do → Doing → Done → To do), swipe left or press and hold for the actions sheet (Open, Move to, Delete). Each card sits in a `.card-wrap` so a coloured hint shows behind it as it slides |
| Task drawer on the right | The `<dialog>` becomes a full-screen page that slides in from the right. `.panel-body` is the one scroller and the composer is `position: sticky` at the bottom. Opening a task pushes a history entry, so the phone's Back button or back gesture closes it; the ‹ button and a swipe right from the left edge do the same |
| Modal dialogs | Bottom sheets (drag the grab handle down, or tap the dimmed area, to dismiss) |

The on-screen keyboard is handled with `window.visualViewport`: `gestures.ts` sets `--kb` (the keyboard's height) while a field is focused, and the CSS lifts sheets and the task page above it. Inputs are 16 px so iOS doesn't zoom. Safe-area insets keep the tab bar clear of the home indicator.

### Installing it on a phone

`index.html` links `/manifest.webmanifest` (served by `app.py` from `static/manifest.webmanifest`, `display: standalone`) and sets the Apple meta tags, so "Add to Home Screen" gives an icon that opens the app without browser chrome. Icons are in `static/icons/` (`icon.svg` is the source; the PNGs are full-bleed squares because iOS and Android apply their own rounding). The only service worker is `static/sw.js` (served at `/sw.js`), which exists solely to hand desktop alerts to the operating system and open the right task when one is clicked. It caches nothing, and the app doesn't work offline. The installed app on iOS has its own cookie storage, so each person signs in once more inside it.

## Notifications

`store._notify` runs inside every task change (see [data-model.md](data-model.md)). The client shows them in three ways:

- **The bell and list** (`Notifications.tsx`): a popover under the bell on desktop and the Alerts tab on a phone. Consecutive changes to one task are folded into one row (`groupNotifications` in `util.ts`); a row can be opened (which marks all its changes read), marked read or unread, or dismissed, and there are "Mark all read" and "Clear read" (which asks first). The title and tools are sticky, only the first eight rows show until "Show older", and the desktop-alerts strip appears only while there is something to set up. All of it is `/api/notifications` calls filtered by the signed-in person's id.
- **Announcements** (`state.ts` `refreshNotifications`, `alerts.ts`): each open tab remembers in memory the newest notification it has shown, so two tabs never take each other's messages, and a hidden tab waits and announces when it becomes visible. Messages are not shown while the list itself is open. A message is **sticky** (stays until dismissed) when the API says so (`sticky`: assigned, removed, deleted, or a due-date change); others fade after 15 seconds. More than three at once become one "N changes" message. Desktop (OS) alerts use a marker shared between tabs (`tb-os-alerted-<id>` in `localStorage`) so each one fires once, and only when the window isn't focused. Clicking either opens the task. The tab title shows the unread count, and every badge uses one cap, "99+".
- **Settings**: a form (user menu, the bell's "Settings" link, or the phone's Me tab) where each person picks, per kind of change, *Alert and bell*, *Bell only* or *Nothing* (API values `alert`, `inbox`, `off`), with "Saved ✓" beside the changed row, saved on every click through `PATCH /api/me/notification-settings`.

Desktop alerts need HTTPS (already provided by `tailscale serve`) and a one-time browser permission, requested from a button click.

## Web Push (alerts when the board is closed)

`push.py` sends them; `static/sw.js` shows them. Pressing *Turn on alerts on this device* (`enablePush` in `alerts.ts`) registers the service worker, asks the browser for permission, subscribes with the server's public key (`GET /api/push`) and saves the result (`PUT /api/push/subscription`). Each phone or computer has its own row in `push_subscriptions`.

After a change is saved, `Pusher.loop` (started in `lifespan`, woken by the same hub as live updates, plus every 30 seconds as a safety net) finds notifications with `pushed_at IS NULL`, builds a short message for each person whose mode is "alert", encrypts it with `pywebpush` and posts it to Apple, Google or Mozilla's push service, which wakes the device. Every notification is then stamped handled, so a restart never repeats one, and anything older than 10 minutes is stamped without being sent. A 404 or 410 deletes the subscription; any other failure is logged and skipped. Tests replace `Pusher.send` with a recorder.

**On a device with push turned on, the page shows no popup or desktop alert of its own** (`systemAlerts()` in `alerts.ts`, checked in `refreshNotifications`): the system banner is the only alert, and the page shows just the bell number and, where supported, the app-icon badge. A device without push keeps the on-page message and desktop alert. The service worker always shows what it is sent (iOS requires every push to show something), using the tag `n-<id>` and `requireInteraction` for sticky kinds. Each person chooses whether banners carry the task's title (`users.push_details`, `PATCH /api/push`); when off they read "A task changed". The app's signing key lives in `app_settings`, so backups carry it. Settings: `PUSH` (on by default) and `PUSH_CONTACT`.

## Updates

`updates.py` only *looks* for a newer version: `git fetch origin main` in the app folder, then the number of commits behind and their subjects, never touching the working files. A `Checker` keeps the last answer and a background loop (in the app's `lifespan`, like the nightly backup) repeats it every `UPDATE_CHECK_HOURS` and tells open pages through the `updates` event topic. Admins get it from `GET /api/update`, can look now with `POST /api/update/check`, and turn automatic nightly updates on or off with `PATCH /api/update` (stored in `app_settings`). The client shows it in the admin-only Updates window (`UpdatesDialog`).

Installing is not done by the app. `deploy/windows/update.ps1` does it (by hand, or nightly with `-Auto` from the `TaskBoardUpdate` task), because it has to stop and restart the app and put the old version back if the new one fails. In `-Auto` mode the script reads the admins' choice through the command `simple-task-management update-setting` and leaves `data\update-last-run.json`, which `updates.read_last_run` shows in the same window.

## The JSON API

`/api` is the only way the client reads and changes data, and it is open to any other client too (a phone app, a script). It calls the same `store.*` functions every rule lives in, so rules and history events exist in one place. Every response has a model in `schemas.py`, so the schema published at `/api/openapi.json` describes each one exactly, and the client's TypeScript types are generated from it (`npm run types` in `web/`).

| Area | Endpoints |
|---|---|
| Session | `POST /api/session` (returns a bearer `token` and sets the cookie), `DELETE /api/session` |
| Me | `GET /api/me`, `PATCH /api/me` (theme), `POST /api/me/password`, `GET /api/meta` (labels, choices and the firm's date today) |
| Board | `GET /api/board?who=&done_days=`, `GET /api/summary?who=` |
| Tasks | `POST /api/tasks`, `GET`, `PATCH` and `DELETE /api/tasks/{id}`, `POST /api/tasks/{id}/updates` |
| People | `GET /api/people`, and for admins `POST /api/people`, `PATCH /api/people/{id}`, `POST /api/people/{id}/reset-password`, `DELETE /api/people/{id}` |
| Notifications | `GET /api/notifications?after=&unread=&announce=`, `GET /api/notifications/unread`, `POST .../{id}/read` and `/unread`, `POST .../read-all`, `DELETE .../{id}`, `DELETE /api/notifications` (clear read), `GET` and `PATCH /api/me/notification-settings` |
| Updates | Admins only: `GET /api/update`, `POST /api/update/check`, `PATCH /api/update` (`auto_update`) |
| Live | `GET /api/events` (Server-Sent Events) |

`who` is `me`, `all`, `none` (unassigned) or a user id. Unknown values fall back to `me`.

Conventions: JSON in, JSON out; errors are always `{"error": "message"}` with `400` (our rules), `401`, `403`, `404` or `422` (missing or unknown fields); unknown request fields are rejected. The browser uses its session cookie, and then unsafe requests need the `X-CSRF-Token` header (from `GET /api/me`); other clients can send `Authorization: Bearer <token>` and need no CSRF header. `PATCH /api/tasks/{id}` takes any subset of title, notes, due, repeat, status and assignee_ids, validates all of them before applying any, and returns `next_task_id` when finishing a recurring task created the next occurrence. A person who still has a temporary password can only call `POST /api/me/password`.

## Security model (summary)

- **Network:** the app listens only on localhost, and Tailscale Serve handles HTTPS. Everyone at the firm shares one Tailscale login, so Tailscale can't tell people apart. That's why the app has its own accounts.
- **Sessions:** a random 32-byte token in an `HttpOnly`, `SameSite=Lax` cookie (with `Secure` when the request is HTTPS), stored in the `sessions` table with a 30-day expiry.
- **CSRF:** each session has its own `csrf_token`, returned by `GET /api/me`. The client sends it as `X-CSRF-Token` on every write, and the API checks it for cookie sessions. Sign-in only accepts JSON, which a cross-site form can't send.
- **Passwords:** stdlib `hashlib.scrypt` with a per-user salt. Repeated failed logins for the same username are slowed down (`LoginThrottle`).
- **Output escaping:** Preact escapes everything it renders. The API returns user text untouched (never HTML), and the client turns `#42` references into links by splitting the text, never by building HTML strings. Keep it that way: don't use `dangerouslySetInnerHTML` for anything a person typed.

More detail is in [operations.md](operations.md).
