"""Data access for tasks, assignees, updates and people.

Every write that changes a task also records an ``event`` row in that task's updates thread,
inside the same transaction, so the history can never disagree with the task itself.
"""

import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import auth, dates
from .db import now_iso
from .recurrence import REPEAT_LABELS, REPEATS, next_due

STATUSES = ("todo", "doing", "done")
STATUS_LABELS = {"todo": "To do", "doing": "Doing", "done": "Done"}
MAX_TITLE = 200
MAX_TEXT = 5000
USERNAME_RE = re.compile(r"^[a-z0-9._-]{2,32}$")


class UserError(Exception):
    """A problem with the user's input; its message is shown to them as-is."""


# ---------------------------------------------------------------- validation


def clean_title(title: str) -> str:
    """Trim and validate a task title."""
    title = " ".join(title.split())
    if not title:
        raise UserError("A task needs a title.")
    if len(title) > MAX_TITLE:
        raise UserError(f"Titles can be at most {MAX_TITLE} characters.")
    return title


def clean_text(text: str, what: str, *, required: bool = False) -> str:
    """Trim and length-check free text such as notes and comments."""
    text = text.strip()
    if required and not text:
        raise UserError(f"{what} can't be empty.")
    if len(text) > MAX_TEXT:
        raise UserError(f"{what} can be at most {MAX_TEXT} characters.")
    return text


def parse_due(value: str) -> date:
    """Parse a ``YYYY-MM-DD`` due date from a form field."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise UserError("Please pick a valid due date.") from None


def check_repeat(value: str) -> str:
    """Validate a repeat setting."""
    if value not in REPEATS:
        raise UserError("Unknown repeat setting.")
    return value


def check_status(value: str) -> str:
    """Validate a status value."""
    if value not in STATUSES:
        raise UserError("Unknown status.")
    return value


# ---------------------------------------------------------------- people


def active_people(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All active users, alphabetically."""
    return conn.execute(
        "SELECT * FROM users WHERE is_active = 1 ORDER BY name COLLATE NOCASE"
    ).fetchall()


def get_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    """Look up any user (active or not) by id."""
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def user_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    """Look up an active user by username (case-insensitive)."""
    return conn.execute(
        "SELECT * FROM users WHERE username = ? AND is_active = 1", (username.strip(),)
    ).fetchone()


def create_user(
    conn: sqlite3.Connection,
    name: str,
    username: str,
    password: str,
    *,
    is_admin: bool = False,
    must_change_password: bool = True,
) -> int:
    """Insert a user and return their id."""
    name = " ".join(name.split())
    username = username.strip().lower()
    if not name or len(name) > 60:
        raise UserError("Please enter a name (up to 60 characters).")
    if not USERNAME_RE.match(username):
        raise UserError("Usernames are 2-32 characters: lowercase letters, digits, . _ or -.")
    existing = conn.execute(
        "SELECT id, is_active FROM users WHERE username = ?", (username,)
    ).fetchone()
    if existing and existing["is_active"]:
        raise UserError(f"The username “{username}” is already taken.")
    if existing:
        # Someone removed earlier is coming back: restore their account (and history).
        with conn:
            conn.execute(
                """UPDATE users SET name = ?, password_hash = ?, is_admin = ?, is_active = 1,
                                    must_change_password = ? WHERE id = ?""",
                (
                    name,
                    auth.hash_password(password),
                    int(is_admin),
                    int(must_change_password),
                    existing["id"],
                ),
            )
        return existing["id"]
    with conn:
        cur = conn.execute(
            """INSERT INTO users (name, username, password_hash, is_admin, must_change_password,
                                  created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                name,
                username,
                auth.hash_password(password),
                int(is_admin),
                int(must_change_password),
                now_iso(),
            ),
        )
    return cur.lastrowid


def set_password(
    conn: sqlite3.Connection, user_id: int, password: str, *, must_change: bool = False
) -> None:
    """Replace a user's password; a temporary one forces a change at next sign-in."""
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        raise UserError(f"Passwords need at least {auth.MIN_PASSWORD_LENGTH} characters.")
    with conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?",
            (auth.hash_password(password), int(must_change), user_id),
        )


def reset_password(conn: sqlite3.Connection, user_id: int) -> str:
    """Give a user a new temporary password, sign them out everywhere, and return it."""
    password = auth.temp_password()
    set_password(conn, user_id, password, must_change=True)
    with conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return password


def set_theme(conn: sqlite3.Connection, user_id: int, theme: str) -> None:
    """Save a user's theme choice."""
    if theme not in ("system", "light", "dark"):
        raise UserError("Unknown theme.")
    with conn:
        conn.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, user_id))


def _active_admin_count(conn: sqlite3.Connection) -> int:
    """Number of active admins."""
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_active = 1"
    ).fetchone()[0]


def set_admin(conn: sqlite3.Connection, user_id: int, is_admin: bool) -> None:
    """Grant or revoke admin, refusing to remove the last active admin."""
    target = get_user(conn, user_id)
    if not target or not target["is_active"]:
        raise UserError("That person no longer exists.")
    if not is_admin and target["is_admin"] and _active_admin_count(conn) <= 1:
        raise UserError("There must always be at least one admin.")
    with conn:
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id))


def remove_person(conn: sqlite3.Connection, actor: sqlite3.Row, user_id: int) -> None:
    """Deactivate a user, sign them out, and take them off every open task."""
    target = get_user(conn, user_id)
    if not target or not target["is_active"]:
        raise UserError("That person has already been removed.")
    if target["id"] == actor["id"]:
        raise UserError("You can't remove yourself.")
    if target["is_admin"] and _active_admin_count(conn) <= 1:
        raise UserError("There must always be at least one admin.")
    now = now_iso()
    with conn:
        open_ids = [
            r[0]
            for r in conn.execute(
                """SELECT a.task_id FROM task_assignees a JOIN tasks t ON t.id = a.task_id
                   WHERE a.user_id = ? AND t.status != 'done'""",
                (user_id,),
            )
        ]
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        for task_id in open_ids:
            conn.execute(
                "DELETE FROM task_assignees WHERE task_id = ? AND user_id = ?", (task_id, user_id)
            )
            _event(
                conn, task_id, actor["id"], f"removed {target['name']} (no longer on the team)", now
            )


# ---------------------------------------------------------------- reading tasks


def _who_clause(who: str, me: int) -> tuple[str, list]:
    """SQL fragment and params for the board's "Showing" filter."""
    if who == "all":
        return "", []
    if who == "none":
        return "AND NOT EXISTS (SELECT 1 FROM task_assignees a WHERE a.task_id = t.id)", []
    try:
        user_id = me if who == "me" else int(who)
    except ValueError:
        user_id = me
    return (
        "AND EXISTS (SELECT 1 FROM task_assignees a WHERE a.task_id = t.id AND a.user_id = ?)",
        [user_id],
    )


def assignees_for(conn: sqlite3.Connection, task_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
    """Map task id -> its assignees (id, name), ordered by name."""
    result: dict[int, list[sqlite3.Row]] = defaultdict(list)
    if not task_ids:
        return result
    marks = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"""SELECT a.task_id, u.id, u.name FROM task_assignees a JOIN users u ON u.id = a.user_id
            WHERE a.task_id IN ({marks}) ORDER BY u.name COLLATE NOCASE""",
        task_ids,
    )
    for row in rows:
        result[row["task_id"]].append(row)
    return result


def _comment_counts(conn: sqlite3.Connection, task_ids: list[int]) -> dict[int, int]:
    """Map task id -> number of comments (not events)."""
    if not task_ids:
        return {}
    marks = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"""SELECT task_id, COUNT(*) FROM updates WHERE kind = 'comment' AND task_id IN ({marks})
            GROUP BY task_id""",
        task_ids,
    )
    return {r[0]: r[1] for r in rows}


def _card(row: sqlite3.Row, people: list, comments: int, today: date, tz: ZoneInfo) -> dict:
    """Shape a task row into what the card template needs."""
    due = date.fromisoformat(row["due_date"])
    if row["status"] == "done" and row["done_at"]:
        done_on = dates.local_date(row["done_at"], tz)
        label, tone = f"Done {done_on.day} {done_on:%b}", "green"
    else:
        label, tone = dates.due_label(due, today)
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "due": due,
        "due_label": label,
        "due_tone": tone,
        "repeat": row["repeat"],
        "repeat_label": REPEAT_LABELS[row["repeat"]],
        "assignees": people,
        "comments": comments,
    }


def board(
    conn: sqlite3.Connection,
    *,
    who: str,
    me: int,
    today: date,
    tz: ZoneInfo,
    done_days: int = 14,
) -> dict[str, list[dict]]:
    """Cards for the three columns. Open columns sort by due date; Done by most recent."""
    clause, params = _who_clause(who, me)
    cutoff = datetime.combine(today - timedelta(days=done_days), datetime.min.time(), tz)
    rows = conn.execute(
        f"""SELECT t.* FROM tasks t
            WHERE (t.status != 'done' OR t.done_at >= ?) {clause}
            ORDER BY CASE WHEN t.status = 'done' THEN t.done_at END DESC, t.due_date, t.id""",
        [cutoff.isoformat(timespec="seconds"), *params],
    ).fetchall()
    ids = [r["id"] for r in rows]
    people, comments = assignees_for(conn, ids), _comment_counts(conn, ids)
    columns: dict[str, list[dict]] = {s: [] for s in STATUSES}
    for r in rows:
        columns[r["status"]].append(_card(r, people[r["id"]], comments.get(r["id"], 0), today, tz))
    return columns


def summary(conn: sqlite3.Connection, *, who: str, me: int, today: date) -> dict[str, list[dict]]:
    """Open tasks that are overdue, due today, or due within the next few days."""
    clause, params = _who_clause(who, me)
    horizon = today + timedelta(days=dates.SOON_DAYS)
    rows = conn.execute(
        f"""SELECT t.id, t.title, t.due_date, t.repeat FROM tasks t
            WHERE t.status != 'done' AND t.due_date <= ? {clause}
            ORDER BY t.due_date, t.id""",
        [horizon.isoformat(), *params],
    ).fetchall()
    buckets: dict[str, list[dict]] = {"overdue": [], "today": [], "soon": []}
    for r in rows:
        due = date.fromisoformat(r["due_date"])
        buckets[dates.bucket(due, today)].append(
            {"id": r["id"], "title": r["title"], "due": due, "repeat": r["repeat"]}
        )
    return buckets


def get_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    """Fetch one task row."""
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def thread(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    """A task's comments and events, oldest first, with author names."""
    return conn.execute(
        """SELECT u.id AS update_id, u.kind, u.body, u.created_at, u.author_id,
                  a.name AS author_name
           FROM updates u LEFT JOIN users a ON a.id = u.author_id
           WHERE u.task_id = ? ORDER BY u.created_at, u.id""",
        (task_id,),
    ).fetchall()


def series(conn: sqlite3.Connection, task: sqlite3.Row) -> list[sqlite3.Row]:
    """Other occurrences in the same recurring chain, newest due date first."""
    if task["series_id"] is None:
        return []
    return conn.execute(
        """SELECT id, title, due_date, status FROM tasks
           WHERE series_id = ? AND id != ? ORDER BY due_date DESC LIMIT 12""",
        (task["series_id"], task["id"]),
    ).fetchall()


# ---------------------------------------------------------------- writing tasks


def _event(
    conn: sqlite3.Connection, task_id: int, author_id: int | None, body: str, at: str
) -> None:
    """Append an automatic history entry to a task's thread."""
    conn.execute(
        "INSERT INTO updates (task_id, author_id, kind, body, created_at) VALUES (?, ?, 'event', ?, ?)",
        (task_id, author_id, body, at),
    )


def _check_assignees(conn: sqlite3.Connection, ids: list[int]) -> list[int]:
    """De-duplicate assignee ids and make sure each is an active user."""
    unique = list(dict.fromkeys(ids))
    if not unique:
        return []
    marks = ",".join("?" * len(unique))
    found = {
        r[0]
        for r in conn.execute(
            f"SELECT id FROM users WHERE is_active = 1 AND id IN ({marks})", unique
        )
    }
    if len(found) != len(unique):
        raise UserError("One of the selected people no longer exists. Reload the page.")
    return unique


def _names(conn: sqlite3.Connection, ids: list[int]) -> str:
    """Comma-separated names for a list of user ids, in the given order."""
    by_id = {r["id"]: r["name"] for r in active_people(conn)}
    return ", ".join(by_id.get(i, "?") for i in ids)


def create_task(
    conn: sqlite3.Connection,
    actor: sqlite3.Row,
    *,
    title: str,
    due: str,
    notes: str = "",
    repeat: str = "none",
    assignee_ids: list[int] | None = None,
) -> int:
    """Create a task with its assignees and a "created this" event; return its id."""
    title = clean_title(title)
    notes = clean_text(notes, "Notes")
    due_date = parse_due(due)
    repeat = check_repeat(repeat)
    ids = _check_assignees(conn, assignee_ids or [])
    now = now_iso()
    with conn:
        cur = conn.execute(
            """INSERT INTO tasks (title, notes, due_date, repeat, repeat_day, created_by,
                                  created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                notes,
                due_date.isoformat(),
                repeat,
                due_date.day if repeat != "none" else None,
                actor["id"],
                now,
                now,
            ),
        )
        task_id = cur.lastrowid
        conn.execute("UPDATE tasks SET series_id = ? WHERE id = ?", (task_id, task_id))
        conn.executemany(
            "INSERT INTO task_assignees (task_id, user_id, added_at) VALUES (?, ?, ?)",
            [(task_id, uid, now) for uid in ids],
        )
        parts = ["created this"]
        if ids:
            parts.append(f"assigned {_names(conn, ids)}")
        if repeat != "none":
            parts.append(f"repeats {repeat}")
        _event(conn, task_id, actor["id"], " · ".join(parts), now)
    return task_id


def _require_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
    """Fetch a task or raise a friendly error if it was deleted."""
    task = get_task(conn, task_id)
    if task is None:
        raise UserError("That task no longer exists.")
    return task


def update_task(
    conn: sqlite3.Connection,
    actor: sqlite3.Row,
    task_id: int,
    *,
    title: str | None = None,
    notes: str | None = None,
    due: str | None = None,
    repeat: str | None = None,
    today: date,
) -> None:
    """Change any of title / notes / due date / repeat, logging an event per real change."""
    task = _require_task(conn, task_id)
    changes: dict[str, object] = {}
    events: list[str] = []

    if title is not None and (new := clean_title(title)) != task["title"]:
        changes["title"] = new
        events.append(f"renamed this from “{task['title']}”")
    if notes is not None and (new := clean_text(notes, "Notes")) != task["notes"]:
        changes["notes"] = new
        events.append("edited the notes")

    new_repeat = check_repeat(repeat) if repeat is not None else task["repeat"]
    new_due = parse_due(due) if due is not None else date.fromisoformat(task["due_date"])
    if new_due.isoformat() != task["due_date"]:
        changes["due_date"] = new_due.isoformat()
        old = date.fromisoformat(task["due_date"])
        events.append(
            f"changed the due date from {dates.short_date(old, today)} to "
            f"{dates.short_date(new_due, today)}"
        )
        if new_repeat != "none":
            changes["repeat_day"] = new_due.day
    if new_repeat != task["repeat"]:
        changes["repeat"] = new_repeat
        if new_repeat == "none":
            changes["repeat_day"] = None
            events.append("stopped this repeating")
        else:
            changes.setdefault("repeat_day", task["repeat_day"] or new_due.day)
            events.append(f"set this to repeat {new_repeat}")

    if not changes:
        return
    now = now_iso()
    changes["updated_at"] = now
    sets = ", ".join(f"{k} = ?" for k in changes)
    with conn:
        conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", [*changes.values(), task_id])
        for body in events:
            _event(conn, task_id, actor["id"], body, now)


def set_assignees(
    conn: sqlite3.Connection, actor: sqlite3.Row, task_id: int, assignee_ids: list[int]
) -> None:
    """Replace a task's assignees, logging who was added and removed."""
    _require_task(conn, task_id)
    wanted = _check_assignees(conn, assignee_ids)
    current = [
        r[0]
        for r in conn.execute("SELECT user_id FROM task_assignees WHERE task_id = ?", (task_id,))
    ]
    added = [i for i in wanted if i not in current]
    removed = [i for i in current if i not in wanted]
    if not added and not removed:
        return
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM users")}
    parts = [f"added {names[i]}" for i in added] + [f"removed {names[i]}" for i in removed]
    now = now_iso()
    with conn:
        conn.executemany(
            "INSERT INTO task_assignees (task_id, user_id, added_at) VALUES (?, ?, ?)",
            [(task_id, i, now) for i in added],
        )
        conn.executemany(
            "DELETE FROM task_assignees WHERE task_id = ? AND user_id = ?",
            [(task_id, i) for i in removed],
        )
        conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (now, task_id))
        _event(conn, task_id, actor["id"], " · ".join(parts), now)


def move_task(
    conn: sqlite3.Connection, actor: sqlite3.Row, task_id: int, status: str, today: date
) -> int | None:
    """Change a task's status. Returns the id of a newly created next occurrence, if any."""
    task = _require_task(conn, task_id)
    status = check_status(status)
    if status == task["status"]:
        return None
    if status == "done":
        body = "marked this Done"
    elif task["status"] == "done":
        body = f"reopened this (moved to {STATUS_LABELS[status]})"
    else:
        body = f"moved this to {STATUS_LABELS[status]}"
    now = now_iso()
    with conn:
        conn.execute(
            "UPDATE tasks SET status = ?, done_at = ?, updated_at = ? WHERE id = ?",
            (status, now if status == "done" else None, now, task_id),
        )
        _event(conn, task_id, actor["id"], body, now)
        if status == "done" and task["repeat"] != "none":
            return _spawn_next(conn, task, now, today)
    return None


def _spawn_next(conn: sqlite3.Connection, task: sqlite3.Row, now: str, today: date) -> int | None:
    """Create the next occurrence of a recurring task (caller holds the transaction)."""
    if conn.execute("SELECT 1 FROM tasks WHERE prev_task_id = ?", (task["id"],)).fetchone():
        return None  # reopened and closed again: the next one already exists
    due = date.fromisoformat(task["due_date"])
    nxt = next_due(due, task["repeat"], task["repeat_day"])
    cur = conn.execute(
        """INSERT INTO tasks (title, notes, due_date, repeat, repeat_day, series_id, prev_task_id,
                              created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            task["title"],
            task["notes"],
            nxt.isoformat(),
            task["repeat"],
            task["repeat_day"],
            task["series_id"] or task["id"],
            task["id"],
            task["created_by"],
            now,
            now,
        ),
    )
    new_id = cur.lastrowid
    conn.execute(
        """INSERT INTO task_assignees (task_id, user_id, added_at)
           SELECT ?, a.user_id, ? FROM task_assignees a JOIN users u ON u.id = a.user_id
           WHERE a.task_id = ? AND u.is_active = 1""",
        (new_id, now, task["id"]),
    )
    _event(
        conn,
        task["id"],
        None,
        f"Next occurrence created: #{new_id}, due {dates.short_date(nxt, today)}",
        now,
    )
    _event(
        conn,
        new_id,
        None,
        f"Continued from #{task['id']} (due {dates.short_date(due, today)}) · repeats {task['repeat']}",
        now,
    )
    return new_id


def add_comment(conn: sqlite3.Connection, actor: sqlite3.Row, task_id: int, body: str) -> None:
    """Post a comment / progress update on a task."""
    _require_task(conn, task_id)
    body = clean_text(body, "An update", required=True)
    now = now_iso()
    with conn:
        conn.execute(
            "INSERT INTO updates (task_id, author_id, kind, body, created_at) VALUES (?, ?, 'comment', ?, ?)",
            (task_id, actor["id"], body, now),
        )
        conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (now, task_id))


def delete_task(conn: sqlite3.Connection, task_id: int) -> None:
    """Permanently delete a task and its thread (for cleaning up mistakes)."""
    with conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
