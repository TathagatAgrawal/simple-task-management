"""Print the JSON API's OpenAPI schema to stdout; ``npm run types`` turns it into TypeScript types."""

import json
import sys
import tempfile
from pathlib import Path

from simple_task_management.app import create_app
from simple_task_management.config import Settings


def main() -> None:
    """Build the app against a throwaway data directory and print the API's schema."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = Settings(
            data_dir=root / "data",
            backup_dir=root / "backups",
            log_dir=root / "logs",
            backups_enabled=False,
        )
        app = create_app(settings)
        api = next(route.app for route in app.routes if getattr(route, "path", "") == "/api")
        json.dump(api.openapi(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
