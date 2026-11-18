"""Runtime settings, read from environment variables and an optional ``.env`` file."""

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    """All configurable knobs for one running instance of the app."""

    data_dir: Path
    backup_dir: Path
    log_dir: Path
    timezone: str = "Asia/Kolkata"
    backup_hour: int = 23
    backup_keep: int = 30
    backups_enabled: bool = True
    # Look for a newer version on GitHub every few hours (it only looks; update.ps1 installs).
    update_check_enabled: bool = False
    update_check_hours: float = 6

    @property
    def db_path(self) -> Path:
        """Location of the live SQLite database."""
        return self.data_dir / "tasks.db"

    @property
    def tz(self) -> ZoneInfo:
        """The firm's timezone, used for "today" and for displaying timestamps."""
        return ZoneInfo(self.timezone)


def _read_dotenv(path: Path) -> dict[str, str]:
    """Parse simple ``KEY=VALUE`` lines from a ``.env`` file, ignoring comments and blanks."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_settings(base_dir: Path | None = None) -> Settings:
    """Build settings from ``.env`` in ``base_dir`` (default: cwd), overridden by the environment.

    Relative paths are resolved against ``base_dir`` so the app behaves the same however it
    is launched (terminal, Task Scheduler, tests).
    """
    base = (base_dir or Path.cwd()).resolve()
    env = _read_dotenv(base / ".env") | dict(os.environ)

    def path(key: str, default: str) -> Path:
        """Resolve a directory setting relative to the base directory."""
        p = Path(env.get(key, default)).expanduser()
        return p if p.is_absolute() else base / p

    return Settings(
        data_dir=path("DATA_DIR", "data"),
        backup_dir=path("BACKUP_DIR", "backups"),
        log_dir=path("LOG_DIR", "logs"),
        timezone=env.get("TIMEZONE", "Asia/Kolkata"),
        backup_hour=int(env.get("BACKUP_HOUR", "23")),
        backup_keep=int(env.get("BACKUP_KEEP", "30")),
        backups_enabled=env.get("BACKUPS_ENABLED", "1") not in {"0", "false", "no"},
        update_check_enabled=env.get("UPDATE_CHECK", "1") not in {"0", "false", "no"},
        update_check_hours=float(env.get("UPDATE_CHECK_HOURS", "6")),
    )
