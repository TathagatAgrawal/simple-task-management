"""Looking for a newer version of the app on GitHub.

This module only *looks*: ``git fetch`` and a comparison. Installing a new version stops and
restarts the app, which needs an administrator, so it is done by ``deploy/windows/update.ps1``
(by hand, or nightly when "update automatically" is on). The script leaves a note about its last
run in the data folder, which ``read_last_run`` shows to the admins.
"""

import asyncio
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .db import now_iso
from .events import Hub

APP_DIR = Path(__file__).resolve().parents[2]
LAST_RUN_FILE = "update-last-run.json"
FIRST_CHECK_DELAY_SECONDS = 60


@dataclass
class Status:
    """What the last look at GitHub found."""

    supported: bool
    behind: int = 0
    current: str = ""
    latest: str = ""
    commits: list[str] = field(default_factory=list)
    checked_at: str | None = None
    error: str | None = None


def _git(app_dir: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    """Run git in the app folder without ever waiting for someone to type (and without a window)."""
    return subprocess.run(
        ["git", *args],
        cwd=app_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )


def check(app_dir: Path = APP_DIR) -> Status:
    """Fetch from GitHub and report how far behind this copy of the app is. Never raises."""
    now = now_iso()
    if not (app_dir / ".git").exists():
        return Status(
            False,
            checked_at=now,
            error="This copy of the app was not installed with git, so it can't look for updates.",
        )
    if shutil.which("git") is None:
        return Status(False, checked_at=now, error="Git is not installed on this PC.")
    try:
        current = _git(app_dir, "rev-parse", "--short", "HEAD").stdout.strip()
        fetched = _git(app_dir, "fetch", "origin", "main", "--quiet")
        if fetched.returncode != 0:
            return Status(
                True,
                current=current,
                checked_at=now,
                error="Couldn't reach GitHub. Check the internet connection and try again.",
            )
        latest = _git(app_dir, "rev-parse", "--short", "origin/main").stdout.strip()
        behind = int(_git(app_dir, "rev-list", "--count", "HEAD..origin/main").stdout.strip() or 0)
        subjects = _git(app_dir, "log", "--format=%s", "-n", "10", "HEAD..origin/main")
        commits = [line for line in subjects.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError, ValueError):
        return Status(True, checked_at=now, error="Couldn't check for updates just now.")
    return Status(True, behind, current, latest, commits, now)


def read_last_run(data_dir: Path) -> dict | None:
    """The note ``update.ps1`` leaves after an automatic run, or None if there is none."""
    try:
        data = json.loads((data_dir / LAST_RUN_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "ran_at" not in data or "result" not in data:
        return None
    return data


class Checker:
    """Remembers the latest look at GitHub and repeats it every few hours in the background."""

    def __init__(self, app_dir: Path = APP_DIR) -> None:
        """Start without a result; the first check happens a minute after the app starts."""
        self.app_dir = app_dir
        self.status: Status | None = None
        self._lock = threading.Lock()

    def check_now(self) -> Status:
        """Look at GitHub now (takes a few seconds) and remember the answer."""
        with self._lock:
            self.status = check(self.app_dir)
            return self.status

    async def loop(self, hours: float, hub: Hub) -> None:
        """Check shortly after start-up and then every ``hours``, telling open pages each time."""
        await asyncio.sleep(FIRST_CHECK_DELAY_SECONDS)
        while True:
            await asyncio.to_thread(self.check_now)
            hub.publish("updates")
            await asyncio.sleep(hours * 3600)
