# Data model

The schema lives in `src/simple_task_management/schema.sql`. SQLite runs in WAL mode with `foreign_keys = ON` and `busy_timeout = 5000`, set in `db.connect()`.

## Tables

```
users ──< task_assignees >── tasks ──< updates
  │                           │  └── prev_task_id ──▶ tasks (next-occurrence chain)
  ├──< sessions               └── created_by ──▶ users
  ├──< notifications >── tasks (task_id becomes NULL if the task is deleted)
  └──< notification_settings
```

### `users`

| Column | Notes |
|---|---|
| `username` | Unique, `COLLATE NOCASE`. Stored lowercase; 2–32 chars of `a-z 0-9 . _ -` |
| `password_hash` | `scrypt$n$r$p$salt_hex$hash_hex` |
| `is_admin` | The only role flag |
| `is_active` | `0` means removed. Rows are never deleted, so names on old updates survive |
| `must_change_password` | `1` after an admin creates or resets the account; the page forces a new password |
| `theme` | `system`, `light` or `dark`. Stored per person, so it follows them between computers |

### `tasks`

| Column | Notes |
|---|---|
| `due_date` | `YYYY-MM-DD` text. A plain date with no time |
| `status` | `todo`, `doing` or `done` (CHECK constraint) |
| `done_at` | UTC timestamp, set when the task moves to `done` and cleared when it's reopened. Drives the Done column's 14-day window |
| `repeat` | `none`, `weekly`, `monthly`, `quarterly` or `yearly` |
| `repeat_day` | Anchor day of the month (1–31) for monthly and longer repeats; `NULL` when not repeating |
| `series_id` | The id of the first task in a recurring chain. A new task gets its own id |
| `prev_task_id` | The occurrence this one was created from. **Unique index**: a task can have at most one successor |

### `task_assignees`

A `(task_id, user_id)` composite primary key (`WITHOUT ROWID`). Zero rows means the task is unassigned. `ON DELETE CASCADE` from `tasks`.

### `updates`

One table for both kinds of thread entry:

- `kind = 'comment'`: written by a person.
- `kind = 'event'`: automatic history. `author_id` is the person who made the change, or `NULL` for system entries such as "Next occurrence created".

An event's `body` is the **predicate only**, for example `moved this to Doing`. The template prefixes the author's name. Bodies may contain `#123`, which the `link_tasks` filter turns into a link that opens that task.

### `notifications`

An inbox row per person per change they should hear about. `user_id` is the recipient, `actor_id` who made the change, `body` the predicate (for example `moved this to Doing`, `commented: …`), shown after the actor's name. `task_title` keeps the task's name so the row still reads after the task is deleted (`task_id` is then `NULL`, from `ON DELETE SET NULL`). `kind` says what happened (`assigned`, `changed`, `moved`, `comment`, `removed` or `deleted`; the list is `store.NOTIFICATION_KINDS`). `announce` is `0` for an "inbox only" notification: it's listed in the bell but never pops up or sends a desktop alert. `read_at` is `NULL` while unread. `id` is `AUTOINCREMENT` on purpose: the page announces anything newer than the last id it saw, so an id must never be reused after a delete. Rows are private to their recipient, and a person can delete their own freely: the task's thread, not the inbox, is the permanent record.

### `notification_settings`

What each person chose to hear about: `(user_id, kind, mode)`, where `mode` is `alert`, `inbox` or `off`. **A row exists only when the choice differs from the default**, so everyone without rows gets `alert` for every kind, which is how notifications behaved before settings existed. Choosing "Pop up and bell" again deletes the row. Settings are applied when a notification is written (`store._notify`): `off` writes nothing for that person, `inbox` writes it with `announce = 0`.

### `sessions`

`token` (cookie value), `user_id`, `csrf_token`, `expires_at`. Expired rows are purged whenever someone signs in.

## Invariants

These must hold after every change. Tests cover them, so keep it that way.

1. **Every task mutation writes an event in the same transaction** (`with conn:` in `store.py`). Real changes only: saving the same values logs nothing.
2. **At most one next occurrence per task.** This is enforced by the unique index on `prev_task_id` and checked in `_spawn_next`.
3. **There is always at least one active admin.** Admins can't remove themselves, and the last admin can't be demoted or removed.
4. **Removing a person** deletes their sessions and removes them from **open** tasks only, with an event on each. Done tasks keep their historical assignees.
5. **Every task change notifies the task's other assignees, in the same transaction, and never the person who made it** (`store._notify`), unless that recipient turned the kind off in their notification settings. That covers creating a task, editing, moving, commenting, deleting, and changing assignees (added people hear "assigned you to this task", removed people "removed you", the rest who joined or left). Read notifications older than 30 days are deleted whenever a new one is written.
6. **All timestamps are stored as UTC ISO-8601 strings** (`db.now_iso()`) and converted to IST only for display.

## Recurring tasks

The logic is in `store.move_task` → `store._spawn_next` → `recurrence.next_due`.

- When a repeating task moves to **Done** (by drag or button), the next occurrence is created **in the same transaction**. It copies the title, notes, repeat, `repeat_day` and `series_id`, plus the **active** assignees. It starts in To do with `prev_task_id` set to the old task. Both threads get linking events.
- **The next due date counts from the previous due date, not the completion date**, so finishing late doesn't shift the schedule.
- **Month-end anchoring:** `repeat_day` remembers the intended day. With anchor 31 you get 31 Jan → 28 Feb → 31 Mar, not 28 Mar. Weekly repeats ignore the anchor.
- **Manual due-date changes on a repeating task reset the anchor** to the new day. This is how someone handles irregular statutory dates.
- **Reopening and re-closing** doesn't create a duplicate (invariant 2).
- **Stopping** a repeat sets `repeat = 'none'` and `repeat_day = NULL`.
- **Why on completion rather than on a calendar:** it needs no scheduler and never piles up identical overdue copies. The trade-off is that next month's task only appears once this month's is done.

## Dates and time

- The firm's "today" is `dates.today_in(settings.tz, clock())`. In the app it's always reached through the `today()` closure in `create_app`, never through `date.today()`.
- `settings.tz` comes from `TIMEZONE` (default `Asia/Kolkata`).
- Display helpers: `dates.due_label` (chip text and tone), `dates.short_date` (`Mon 17 Nov`, with the year only if it differs), `dates.stamp` (`Today, 4:12 pm`).
- **Windows gotcha:** don't use glibc-only `strftime` flags such as `%-d`. Build the string from `d.day` instead.

## Migrations

`db.migrate()` uses `PRAGMA user_version`:

- Version 0 (an empty file): apply `schema.sql` and set the version to 1.
- Later changes: **append** an SQL string to `db.MIGRATIONS`. Entry *N* (0-based) upgrades version *N+1* to *N+2*. Never edit `schema.sql` for an existing deployment, and never reorder or edit a migration that has shipped.

Migrations run at every startup (`lifespan`) and in every CLI command. `update.ps1` takes a backup before starting the new version. See the recipe in [development.md](development.md#add-a-column-to-tasks).
