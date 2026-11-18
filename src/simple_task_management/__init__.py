"""Command-line entry point: ``serve``, ``create-admin``, ``set-password``, ``seed-demo``, ``backup``."""

import argparse
import copy
import getpass
import logging
import sys
from datetime import UTC, datetime, timedelta
from logging.handlers import TimedRotatingFileHandler

from . import auth, backup, dates, db, store
from .config import Settings, load_settings


def _open_db(settings: Settings):
    """Connect to the configured database and make sure the schema is current."""
    conn = db.connect(settings.db_path)
    db.migrate(conn)
    return conn


def _ask_password(prompt: str = "Password") -> str:
    """Prompt twice for a password without echoing it."""
    while True:
        first = getpass.getpass(f"{prompt} (at least {auth.MIN_PASSWORD_LENGTH} characters): ")
        if len(first) < auth.MIN_PASSWORD_LENGTH:
            print("Too short, try again.")
            continue
        if first == getpass.getpass("Type it again: "):
            return first
        print("They didn't match, try again.")


def _log_config(settings: Settings) -> dict:
    """Uvicorn's logging config plus a daily-rotated file in the log directory (kept 14 days)."""
    from uvicorn.config import LOGGING_CONFIG

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    config = copy.deepcopy(LOGGING_CONFIG)
    config["formatters"]["file"] = {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}
    config["handlers"]["file"] = {
        "class": TimedRotatingFileHandler.__module__ + ".TimedRotatingFileHandler",
        "filename": str(settings.log_dir / "app.log"),
        "when": "midnight",
        "backupCount": 14,
        "encoding": "utf-8",
        "formatter": "file",
    }
    for name in ("uvicorn", "uvicorn.access"):
        config["loggers"][name]["handlers"].append("file")
    config["loggers"]["simple_task_management"] = {
        "handlers": ["default", "file"],
        "level": "INFO",
    }
    return config


def cmd_serve(args: argparse.Namespace, settings: Settings) -> None:
    """Run the web server."""
    import uvicorn

    _open_db(settings).close()
    print(f"Task board on http://{args.host}:{args.port}  (data: {settings.db_path})")
    uvicorn.run(
        "simple_task_management.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        log_config=_log_config(settings),
        timeout_graceful_shutdown=3,  # open event streams would otherwise delay a restart
    )


def cmd_create_admin(args: argparse.Namespace, settings: Settings) -> None:
    """Interactively create an admin account (used once, on first setup)."""
    conn = _open_db(settings)
    name = args.name or input("Full name: ")
    username = args.username or input("Username (e.g. asha): ")
    password = _ask_password()
    try:
        store.create_user(conn, name, username, password, is_admin=True, must_change_password=False)
    except store.UserError as exc:
        sys.exit(f"Error: {exc}")
    print(f"Admin '{username.strip().lower()}' created. Start the app with: serve")


def cmd_set_password(args: argparse.Namespace, settings: Settings) -> None:
    """Reset anyone's password from the host machine (e.g. if the only admin forgets theirs)."""
    conn = _open_db(settings)
    user = store.user_by_username(conn, args.username)
    if not user:
        sys.exit(f"Error: no active user called '{args.username}'.")
    store.set_password(conn, user["id"], _ask_password("New password"))
    print(f"Password for '{user['username']}' updated.")


def cmd_backup(args: argparse.Namespace, settings: Settings) -> None:
    """Take a backup right now (used by the update script before upgrading)."""
    _open_db(settings).close()
    path = backup.backup_now(
        settings.db_path, settings.backup_dir, keep=settings.backup_keep, label=args.label
    )
    print(f"Backup written to {path}")


DEMO_PEOPLE = [
    ("Asha Iyer", "asha", True),
    ("Ravi Kumar", "ravi", False),
    ("Meera Shah", "meera", False),
]
DEMO_PASSWORD = "demo-pass"


def cmd_seed_demo(args: argparse.Namespace, settings: Settings) -> None:
    """Fill an empty database with three people and realistic tasks, for trying the app out."""
    conn = _open_db(settings)
    if conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]:
        sys.exit("Error: the database already has tasks. Use a fresh DATA_DIR for the demo.")
    ids = {}
    for name, username, is_admin in DEMO_PEOPLE:
        existing = store.user_by_username(conn, username)
        ids[username] = (
            existing["id"]
            if existing
            else store.create_user(
                conn, name, username, DEMO_PASSWORD, is_admin=is_admin, must_change_password=False
            )
        )
    asha = store.get_user(conn, ids["asha"])
    ravi = store.get_user(conn, ids["ravi"])
    today = dates.today_in(settings.tz, datetime.now(UTC))

    def day(offset: int) -> str:
        """ISO date ``offset`` days from today."""
        return (today + timedelta(days=offset)).isoformat()

    demo = [
        ("TDS return Q2 - Mehta & Co", -2, "quarterly", ["asha", "meera"], "doing", "Form 24Q."),
        ("GSTR-3B - Patel Traders", 0, "monthly", ["asha"], "todo", ""),
        ("Call bank re: audit letter", 0, "none", ["ravi"], "doing", ""),
        ("ITR - R. Sharma", 2, "none", ["asha"], "todo", "Waiting on Form 16."),
        ("Board minutes draft", 3, "none", ["asha", "ravi"], "todo", ""),
        ("Payroll - this month", 5, "monthly", ["meera"], "todo", ""),
        ("Audit file prep - Iyer", 8, "none", ["ravi"], "todo", ""),
        ("Advance tax reminder emails", 20, "quarterly", [], "todo", ""),
        ("Reconcile Q2 ledger - Iyer", -4, "none", ["asha", "ravi", "meera"], "done", ""),
    ]
    for title, offset, repeat, who, status, notes in demo:
        task_id = store.create_task(
            conn,
            ravi,
            title=title,
            due=day(offset),
            notes=notes,
            repeat=repeat,
            assignee_ids=[ids[w] for w in who],
        )
        if status != "todo":
            store.move_task(conn, asha, task_id, status, today)
        if offset < 0 and status == "doing":
            store.add_comment(conn, asha, task_id, "Emailed the client for the missing details.")
            store.add_comment(
                conn, ravi, task_id, "I'll call them today, they usually reply by phone."
            )
    print("Demo data created. Sign in as asha (admin), ravi or meera with password:", DEMO_PASSWORD)


def main() -> None:
    """Parse the command line and run the chosen sub-command."""
    parser = argparse.ArgumentParser(prog="simple-task-management", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="restart on code changes (dev only)")
    serve.set_defaults(func=cmd_serve)

    admin = sub.add_parser("create-admin", help="create an admin account")
    admin.add_argument("--name")
    admin.add_argument("--username")
    admin.set_defaults(func=cmd_create_admin)

    setpw = sub.add_parser("set-password", help="set someone's password from the host")
    setpw.add_argument("username")
    setpw.set_defaults(func=cmd_set_password)

    bk = sub.add_parser("backup", help="take a database backup now")
    bk.add_argument("--label", default="manual")
    bk.set_defaults(func=cmd_backup)

    seed = sub.add_parser("seed-demo", help="fill an empty database with demo people and tasks")
    seed.set_defaults(func=cmd_seed_demo)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    args.func(args, load_settings())
