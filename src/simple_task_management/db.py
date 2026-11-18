"""SQLite connection handling and schema migrations."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Future schema changes: append SQL strings here. Entry N upgrades user_version N -> N+1.
MIGRATIONS: list[str] = [
    # 1 -> 2: notifications. The text is stored, so it still reads right after the task is
    # deleted (task_id becomes NULL and task_title keeps the name).
    """
    CREATE TABLE notifications (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- never reused, so "newer than id N" holds
        user_id    INTEGER NOT NULL REFERENCES users (id),
        task_id    INTEGER REFERENCES tasks (id) ON DELETE SET NULL,
        task_title TEXT    NOT NULL,
        actor_id   INTEGER REFERENCES users (id),
        body       TEXT    NOT NULL,
        created_at TEXT    NOT NULL,
        read_at    TEXT
    );

    CREATE INDEX notifications_user ON notifications (user_id, id);
    """,
    # 2 -> 3: per-person notification settings. Each notification gets a kind (what happened) and
    # an announce flag (0 = "inbox only": listed in the bell but no pop-up or desktop alert).
    # A person's mode per kind is stored only when it differs from the default ("alert").
    """
    ALTER TABLE notifications ADD COLUMN kind TEXT NOT NULL DEFAULT 'changed';
    ALTER TABLE notifications ADD COLUMN announce INTEGER NOT NULL DEFAULT 1;
    UPDATE notifications SET kind = 'assigned' WHERE body LIKE 'assigned you%';
    UPDATE notifications SET kind = 'removed' WHERE body LIKE 'removed you%';
    UPDATE notifications SET kind = 'comment' WHERE body LIKE 'commented:%';
    UPDATE notifications SET kind = 'deleted' WHERE body = 'deleted this task';
    UPDATE notifications SET kind = 'moved'
        WHERE body = 'marked this Done' OR body LIKE 'moved this to%' OR body LIKE 'reopened this%';

    CREATE TABLE notification_settings (
        user_id INTEGER NOT NULL REFERENCES users (id),
        kind    TEXT    NOT NULL,
        mode    TEXT    NOT NULL CHECK (mode IN ('alert', 'inbox', 'off')),
        PRIMARY KEY (user_id, kind)
    ) WITHOUT ROWID;
    """,
    # 3 -> 4: tasks created before notifications existed. Everyone who is on an open task gets one
    # unread notification for it ("assigned you to this task"), dated when they were added, so
    # the bell shows their current work right after the update and they can read or clear it.
    # They are "bell only" (announce = 0): no pop-up and no desktop alert for old news. Skipped:
    # finished tasks, people who were removed, the person who made the task (they assigned
    # themselves), and anyone who already has a notification about that task.
    """
    INSERT INTO notifications (user_id, task_id, task_title, actor_id, body, kind, announce, created_at)
    SELECT a.user_id, t.id, t.title, t.created_by, 'assigned you to this task', 'assigned', 0, a.added_at
    FROM task_assignees a
    JOIN tasks t ON t.id = a.task_id
    JOIN users u ON u.id = a.user_id AND u.is_active = 1
    WHERE t.status != 'done'
      AND (t.created_by IS NULL OR t.created_by != a.user_id)
      AND NOT EXISTS (
          SELECT 1 FROM notifications n WHERE n.user_id = a.user_id AND n.task_id = t.id
      );
    """,
    # 4 -> 5: small settings the app keeps for itself (for example whether to update automatically).
    """
    CREATE TABLE app_settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    ) WITHOUT ROWID;
    """,
]


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string, the format used for every stored timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with the pragmas the app relies on.

    ``check_same_thread`` is off because FastAPI may run a request's dependency and its
    handler on different worker threads; each connection is still used by one request only.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Bring the database schema up to date and return the resulting version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        version = 1
        conn.execute(f"PRAGMA user_version = {version}")
    for step in MIGRATIONS[version - 1 :]:
        version += 1
        # One transaction per step, version bump included: a step either applies completely or
        # leaves the database exactly as it was, so a failed update can simply be retried.
        try:
            conn.executescript(f"BEGIN;\n{step}\nPRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
    conn.commit()
    return version
