"""Tests for backups, retention and the nightly schedule."""

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from simple_task_management import backup, db, store


def test_backup_is_a_usable_copy(settings, conn, users):
    """The backup file opens and contains the same data."""
    path = backup.backup_now(settings.db_path, settings.backup_dir, label="test")
    copy = sqlite3.connect(path)
    assert copy.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    copy.close()
    assert path.name.endswith("-test.db")


def test_prune_keeps_newest(tmp_path):
    """Only the newest N backups are kept."""
    for day in range(1, 6):
        (tmp_path / f"tasks-2026-11-0{day}-230000.db").write_text("x")
    backup.prune(tmp_path, keep=2)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "tasks-2026-11-04-230000.db",
        "tasks-2026-11-05-230000.db",
    ]


def test_seconds_until_next_backup():
    """The scheduler waits until the next 23:00 in IST."""
    ist = ZoneInfo("Asia/Kolkata")
    assert backup.seconds_until(23, datetime(2026, 11, 14, 22, 0, tzinfo=ist)) == 3600
    assert backup.seconds_until(23, datetime(2026, 11, 14, 23, 0, tzinfo=ist)) == 86400


def test_migrate_is_idempotent(settings, conn):
    """Running migrations again leaves the schema version unchanged."""
    assert db.migrate(conn) == 2
    assert store.active_people(conn) == []
