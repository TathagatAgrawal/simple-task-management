"""Tests for the migration that gives existing tasks their notifications when the app is updated."""

import sqlite3
from pathlib import Path

from simple_task_management import db, store

NOW = "2026-11-10T04:00:00+00:00"


def _old_database(path: Path, *, stop_at: int = 1) -> sqlite3.Connection:
    """A database as an older version left it: people and tasks, at schema version ``stop_at``."""
    conn = db.connect(path)
    conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
    for step in db.MIGRATIONS[: stop_at - 1]:
        conn.executescript(step)
    conn.execute(f"PRAGMA user_version = {stop_at}")
    people = [
        (1, "Asha Iyer", "asha", 1),
        (2, "Ravi Kumar", "ravi", 1),
        (3, "Meera Shah", "meera", 1),
    ]
    for uid, name, username, active in [*people, (4, "Gone Away", "gone", 0)]:
        conn.execute(
            "INSERT INTO users (id, name, username, password_hash, is_active, created_at) "
            "VALUES (?, ?, ?, 'x', ?, ?)",
            (uid, name, username, active, NOW),
        )
    tasks = [
        (1, "GSTR-3B", "todo", 1),  # open, made by Asha, given to Ravi and Meera
        (2, "Own task", "doing", 1),  # Asha assigned it to herself
        (3, "Already done", "done", 1),  # finished: no notification
        (4, "Shared with a removed person", "todo", 1),
        (5, "Nobody's", "todo", 1),  # unassigned
        (6, "No creator recorded", "todo", None),
    ]
    for tid, title, status, creator in tasks:
        conn.execute(
            "INSERT INTO tasks (id, title, due_date, status, created_by, created_at, updated_at) "
            "VALUES (?, ?, '2026-11-20', ?, ?, ?, ?)",
            (tid, title, status, creator, NOW, NOW),
        )
    given = [(1, 2), (1, 3), (2, 1), (3, 2), (4, 2), (4, 4), (6, 2)]
    for tid, uid in given:
        conn.execute(
            "INSERT INTO task_assignees (task_id, user_id, added_at) VALUES (?, ?, ?)",
            (tid, uid, f"2026-11-0{tid}T05:00:00+00:00"),
        )
    conn.commit()
    return conn


def _rows(conn: sqlite3.Connection) -> list[tuple]:
    """Every notification as ``(user id, task id)``, in a stable order."""
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT user_id, task_id FROM notifications ORDER BY user_id, task_id"
        )
    ]


def test_open_tasks_get_one_notification_per_person_on_them(tmp_path):
    """Everyone on an open task is told once; finished, self-assigned and removed are left out."""
    conn = _old_database(tmp_path / "old.db")
    assert db.migrate(conn) == 5
    assert _rows(conn) == [(2, 1), (2, 4), (2, 6), (3, 1)]


def test_backfilled_notifications_are_unread_quiet_and_dated_from_the_assignment(tmp_path):
    """They sit in the bell as unread, never pop up, and keep when the person was added."""
    conn = _old_database(tmp_path / "old.db")
    db.migrate(conn)
    row = conn.execute("SELECT * FROM notifications WHERE user_id = 3 AND task_id = 1").fetchone()
    assert row["read_at"] is None and row["announce"] == 0 and row["kind"] == "assigned"
    assert row["body"] == "assigned you to this task" and row["task_title"] == "GSTR-3B"
    assert row["actor_id"] == 1 and row["created_at"] == "2026-11-01T05:00:00+00:00"
    no_creator = conn.execute("SELECT actor_id FROM notifications WHERE task_id = 6").fetchone()
    assert no_creator["actor_id"] is None


def test_people_see_them_right_away_and_can_clear_or_read_them(tmp_path):
    """The bell counts them, the list shows them, and reading or clearing works as usual."""
    conn = _old_database(tmp_path / "old.db")
    db.migrate(conn)
    assert store.notification_counts(conn, 2)[0] == 3 and store.notification_counts(conn, 3)[0] == 1
    assert store.notification_counts(conn, 1)[0] == 0  # Asha only made her own task
    titles = {n["title"] for n in store.notifications_for(conn, 2)}
    assert titles == {"GSTR-3B", "Shared with a removed person", "No creator recorded"}
    assert store.notifications_for(conn, 2, announce_only=True) == []  # nothing pops up
    store.set_notification_read(conn, 2, None, read=True)
    assert store.notification_counts(conn, 2)[0] == 0
    store.dismiss_notifications(conn, 2, None)
    assert store.notifications_for(conn, 2) == []


def test_running_the_migration_again_adds_nothing(tmp_path):
    """The version number guards it, and the rule itself also skips people already notified."""
    conn = _old_database(tmp_path / "old.db")
    db.migrate(conn)
    db.migrate(conn)
    assert _rows(conn) == [(2, 1), (2, 4), (2, 6), (3, 1)]
    conn.executescript(db.MIGRATIONS[2])  # run the backfill step itself a second time
    assert _rows(conn) == [(2, 1), (2, 4), (2, 6), (3, 1)]


def test_a_database_that_already_has_notifications_gets_no_duplicates(tmp_path):
    """Someone already told about a task (created after notifications arrived) is not told again."""
    conn = _old_database(tmp_path / "old.db", stop_at=3)  # has the notifications tables
    conn.execute(
        "INSERT INTO notifications (user_id, task_id, task_title, actor_id, body, kind, created_at) "
        "VALUES (2, 1, 'GSTR-3B', 1, 'assigned you a new task', 'assigned', ?)",
        (NOW,),
    )
    conn.commit()
    assert db.migrate(conn) == 5
    assert _rows(conn) == [(2, 1), (2, 4), (2, 6), (3, 1)]
    bodies = [
        r[0]
        for r in conn.execute("SELECT body FROM notifications WHERE user_id = 2 AND task_id = 1")
    ]
    assert bodies == ["assigned you a new task"]


def test_a_new_install_has_nothing_to_backfill(tmp_path):
    """An empty database migrates cleanly and starts with no notifications."""
    conn = db.connect(tmp_path / "new.db")
    assert db.migrate(conn) == 5
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


def test_people_who_turned_assigned_notifications_off_are_not_told(tmp_path):
    """The backfill respects a saved choice of "Nothing" for assignments; "Bell only" still gets it."""
    conn = _old_database(tmp_path / "old.db", stop_at=3)
    conn.executemany(
        "INSERT INTO notification_settings (user_id, kind, mode) VALUES (?, ?, ?)",
        [(3, "assigned", "off"), (2, "assigned", "inbox"), (2, "comment", "off")],
    )
    conn.commit()
    db.migrate(conn)
    assert _rows(conn) == [(2, 1), (2, 4), (2, 6)]  # Meera (3) chose Nothing; Ravi did not
    saved = [
        tuple(r)
        for r in conn.execute("SELECT user_id, kind, mode FROM notification_settings ORDER BY 1, 2")
    ]
    assert saved == [
        (2, "assigned", "inbox"),
        (2, "comment", "off"),
        (3, "assigned", "off"),
    ]  # untouched
