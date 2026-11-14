"""SQLite connection handling and schema migrations."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Future schema changes: append SQL strings here. Entry N upgrades user_version N -> N+1.
MIGRATIONS: list[str] = []


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
        conn.executescript(step)
        version += 1
        conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    return version
