"""Online SQLite backups with simple retention, plus the nightly scheduler loop."""

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)
PREFIX = "tasks-"


def backup_now(db_path: Path, backup_dir: Path, *, keep: int = 30, label: str = "") -> Path:
    """Copy the live database into ``backup_dir`` safely and prune old copies.

    Uses SQLite's backup API, which produces a consistent copy even while the app is writing.
    Files are named ``tasks-YYYY-MM-DD-HHMMSS[-label].db`` so they sort by time.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"-{label}" if label else ""
    target = backup_dir / f"{PREFIX}{datetime.now():%Y-%m-%d-%H%M%S}{suffix}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    prune(backup_dir, keep)
    return target


def prune(backup_dir: Path, keep: int) -> None:
    """Delete all but the newest ``keep`` backup files."""
    files = sorted(backup_dir.glob(f"{PREFIX}*.db"))
    for old in files[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)


def seconds_until(hour: int, now: datetime) -> float:
    """Seconds from the aware datetime ``now`` until the next ``hour``:00 in its timezone."""
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def nightly_loop(settings: Settings) -> None:
    """Run forever, taking one backup each night at ``settings.backup_hour``."""
    while True:
        await asyncio.sleep(seconds_until(settings.backup_hour, datetime.now(settings.tz)))
        try:
            path = await asyncio.to_thread(
                backup_now, settings.db_path, settings.backup_dir, keep=settings.backup_keep
            )
            log.info("Nightly backup written to %s", path)
        except Exception:
            log.exception("Nightly backup failed")
