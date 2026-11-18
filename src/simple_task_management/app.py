"""FastAPI application: the single page plus the HTML fragments htmx swaps into it.

Mutating endpoints answer ``204`` with ``HX-Trigger: tasks-changed``; the board, the summary
and the open task panel listen for that event and re-fetch themselves.
"""

import asyncio
import contextlib
import hashlib
import hmac
import json
import re
import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, backup, dates, db, store
from .api import build_api
from .config import Settings, load_settings
from .recurrence import REPEAT_LABELS

HERE = Path(__file__).parent
TASKS_CHANGED = {"HX-Trigger": "tasks-changed"}
NOTIFICATIONS_CHANGED = {"HX-Trigger": "notifications-changed"}
_TASK_REF = re.compile(r"#(\d+)\b")


# ---------------------------------------------------------------- template helpers


def initials(name: str) -> str:
    """Up to two initials for an avatar, e.g. ``Asha Sharma`` -> ``AS``."""
    parts = name.split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def avatar_tone(user_id: int) -> str:
    """Stable colour class for a person's avatar."""
    return "abc"[user_id % 3]


def link_tasks(text: str) -> Markup:
    """Escape text and turn ``#42`` references into links that open that task."""
    # Match on the raw text and escape each piece separately; matching after escaping would
    # turn entities such as &#39; (an apostrophe) into bogus links.
    parts: list[str] = []
    last = 0
    for match in _TASK_REF.finditer(text):
        task_id = match.group(1)
        parts.append(str(escape(text[last : match.start()])))
        parts.append(
            f'<a href="#task-{task_id}" hx-get="/tasks/{task_id}" hx-target="#panel" '
            f'hx-swap="innerHTML">#{task_id}</a>'
        )
        last = match.end()
    parts.append(str(escape(text[last:])))
    return Markup("".join(parts))


def static_fingerprint() -> str:
    """Short hash of the static files, used as a cache-buster.

    Browsers then fetch new CSS/JS after an update even if the package version wasn't bumped.
    """
    digest = hashlib.sha256()
    static = HERE / "static"
    for path in sorted(p for p in static.rglob("*") if p.is_file()):
        digest.update(path.relative_to(static).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def _templates() -> Jinja2Templates:
    """Jinja environment with the app's filters and globals."""
    templates = Jinja2Templates(directory=HERE / "templates")
    env = templates.env
    env.filters["initials"] = initials
    env.filters["avatar_tone"] = avatar_tone
    env.filters["link_tasks"] = link_tasks
    env.globals["version"] = static_fingerprint()
    env.globals["repeat_labels"] = REPEAT_LABELS
    env.globals["status_labels"] = store.STATUS_LABELS
    return templates


# ---------------------------------------------------------------- app factory


def create_app(
    settings: Settings | None = None, clock: Callable[[], datetime] | None = None
) -> FastAPI:
    """Build the app. Tests pass their own settings and a fixed clock."""
    settings = settings or load_settings()
    clock = clock or (lambda: datetime.now(UTC))
    templates = _templates()
    throttle = auth.LoginThrottle()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Migrate the database on startup and run the nightly backup in the background."""
        conn = db.connect(settings.db_path)
        db.migrate(conn)
        conn.close()
        task = (
            asyncio.create_task(backup.nightly_loop(settings)) if settings.backups_enabled else None
        )
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def today() -> date:
        """The firm's current calendar date."""
        return dates.today_in(settings.tz, clock())

    # ------------------------------------------------------------ dependencies

    def get_conn() -> Iterator[sqlite3.Connection]:
        """One SQLite connection per request."""
        conn = db.connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    app.mount(
        "/api",
        build_api(settings=settings, today=today, get_conn=get_conn, throttle=throttle),
    )

    def require_user(request: Request, conn: Conn) -> sqlite3.Row:
        """The signed-in user; checks the CSRF header on every POST."""
        found = auth.session_user(conn, request.cookies.get(auth.COOKIE_NAME))
        if not found:
            raise HTTPException(401)
        user, csrf = found
        if request.method == "POST" and not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", ""), csrf
        ):
            raise HTTPException(403, "Your session changed. Please reload the page.")
        if user["must_change_password"] and request.url.path not in ("/me/password", "/logout"):
            raise HTTPException(401)
        return user

    User = Annotated[sqlite3.Row, Depends(require_user)]

    def require_admin(user: User) -> sqlite3.Row:
        """The signed-in user, who must be an admin."""
        if not user["is_admin"]:
            raise HTTPException(403, "Only admins can manage people.")
        return user

    Admin = Annotated[sqlite3.Row, Depends(require_admin)]

    # ------------------------------------------------------------ error handling

    @app.exception_handler(store.UserError)
    async def user_error(request: Request, exc: store.UserError) -> Response:
        """Show validation problems in the page's error banner."""
        return PlainTextResponse(str(exc), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        """Send signed-out users back to the login page; otherwise return plain text."""
        if exc.status_code == 401:
            if request.headers.get("HX-Request"):
                return Response(status_code=401, headers={"HX-Redirect": "/"})
            return RedirectResponse("/", status_code=303)
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

    def render(request: Request, name: str, **context: object) -> HTMLResponse:
        """Render a template with the request in context."""
        return templates.TemplateResponse(request, name, context)

    # ------------------------------------------------------------ page + auth

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, conn: Conn) -> HTMLResponse:
        """The one page: login, set-password, or the board, depending on the session."""
        found = auth.session_user(conn, request.cookies.get(auth.COOKIE_NAME))
        user, csrf = found or (None, "")
        return render(
            request,
            "index.html",
            user=user,
            csrf=csrf,
            people=store.active_people(conn) if user else [],
            today=today().isoformat(),
        )

    @app.post("/login")
    def login(
        request: Request,
        conn: Conn,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
    ) -> Response:
        """Check credentials and start a 30-day session."""
        if not request.headers.get("HX-Request"):
            raise HTTPException(400, "Please sign in from the app page.")
        throttle.wait(username)
        user = store.user_by_username(conn, username)
        if not user or not auth.verify_password(password, user["password_hash"]):
            throttle.failed(username)
            return HTMLResponse("Wrong username or password.")
        throttle.succeeded(username)
        response = Response(headers={"HX-Redirect": "/"})
        auth.set_session_cookie(response, request, auth.create_session(conn, user["id"]))
        return response

    @app.post("/logout")
    def logout(request: Request, conn: Conn, user: User) -> Response:
        """End this browser's session."""
        auth.end_session(conn, request.cookies.get(auth.COOKIE_NAME))
        response = Response(headers={"HX-Redirect": "/"})
        response.delete_cookie(auth.COOKIE_NAME)
        return response

    @app.post("/me/password")
    def change_password(
        conn: Conn,
        user: User,
        new_password: Annotated[str, Form()],
        confirm_password: Annotated[str, Form()],
        current_password: Annotated[str, Form()] = "",
    ) -> Response:
        """Set a new password; the current one is required unless it was temporary."""
        forced = bool(user["must_change_password"])
        if not forced and not auth.verify_password(current_password, user["password_hash"]):
            raise store.UserError("Your current password is not right.")
        if new_password != confirm_password:
            raise store.UserError("The two new passwords don't match.")
        store.set_password(conn, user["id"], new_password)
        if forced:
            return Response(headers={"HX-Redirect": "/"})
        return HTMLResponse('<p class="ok">Password changed.</p>')

    @app.post("/me/theme", status_code=204)
    def change_theme(conn: Conn, user: User, theme: Annotated[str, Form()]) -> Response:
        """Remember this person's light / dark / system choice."""
        store.set_theme(conn, user["id"], theme)
        return Response(status_code=204)

    # ------------------------------------------------------------ board fragments

    @app.get("/summary", response_class=HTMLResponse)
    def summary(request: Request, conn: Conn, user: User, who: str = "me") -> HTMLResponse:
        """The overdue / today / next-3-days strip."""
        buckets = store.summary(conn, who=who, me=user["id"], today=today())
        return render(
            request, "_summary.html", buckets=buckets, today=today(), due_label=dates.due_label
        )

    @app.get("/board", response_class=HTMLResponse)
    def board(
        request: Request, conn: Conn, user: User, who: str = "me", done_days: int = 14
    ) -> HTMLResponse:
        """The three columns of cards."""
        columns = store.board(
            conn, who=who, me=user["id"], today=today(), tz=settings.tz, done_days=done_days
        )
        return render(request, "_board.html", columns=columns, done_days=done_days, who=who)

    # ------------------------------------------------------------ tasks

    @app.post("/tasks", status_code=204)
    def create_task(
        conn: Conn,
        user: User,
        title: Annotated[str, Form()],
        due: Annotated[str, Form()],
        notes: Annotated[str, Form()] = "",
        repeat: Annotated[str, Form()] = "none",
        assignee_ids: Annotated[list[int] | None, Form()] = None,
    ) -> Response:
        """Create a task from the New task dialog."""
        task_id = store.create_task(
            conn, user, title=title, due=due, notes=notes, repeat=repeat, assignee_ids=assignee_ids
        )
        # Open the new task in the panel, so it's visible even if the current filter hides it.
        trigger = json.dumps({"tasks-changed": None, "task-created": {"id": task_id}})
        return Response(status_code=204, headers={"HX-Trigger": trigger})

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    def task_panel(request: Request, conn: Conn, user: User, task_id: int) -> HTMLResponse:
        """The side panel for one task. Empty if it was deleted, which closes the panel."""
        task = store.get_task(conn, task_id)
        if task is None:
            return HTMLResponse("")
        now_day = today()
        updates = [
            {
                "kind": u["kind"],
                "author_id": u["author_id"],
                "author_name": u["author_name"],
                "body": u["body"],
                "when": dates.stamp(u["created_at"], settings.tz, now_day),
            }
            for u in store.thread(conn, task_id)
        ]
        due = date.fromisoformat(task["due_date"])
        label, tone = dates.due_label(due, now_day)
        return render(
            request,
            "_panel.html",
            task=task,
            assigned={a["id"] for a in store.assignees_for(conn, [task_id])[task_id]},
            people=store.active_people(conn),
            updates=updates,
            series=store.series(conn, task),
            due_label=label if task["status"] != "done" else "",
            due_tone=tone,
            short_date=dates.short_date,
            today=now_day,
            date=date,
        )

    @app.post("/tasks/{task_id}", status_code=204)
    def edit_task(
        conn: Conn,
        user: User,
        task_id: int,
        title: Annotated[str | None, Form()] = None,
        notes: Annotated[str | None, Form()] = None,
        due: Annotated[str | None, Form()] = None,
        repeat: Annotated[str | None, Form()] = None,
    ) -> Response:
        """Save edits from the task panel."""
        store.update_task(
            conn, user, task_id, title=title, notes=notes, due=due, repeat=repeat, today=today()
        )
        return Response(status_code=204, headers=TASKS_CHANGED)

    @app.post("/tasks/{task_id}/move", status_code=204)
    def move_task(conn: Conn, user: User, task_id: int, status: Annotated[str, Form()]) -> Response:
        """Change status, from drag-and-drop or the panel's status buttons."""
        store.move_task(conn, user, task_id, status, today())
        return Response(status_code=204, headers=TASKS_CHANGED)

    @app.post("/tasks/{task_id}/assignees", status_code=204)
    def assign(
        conn: Conn,
        user: User,
        task_id: int,
        assignee_ids: Annotated[list[int] | None, Form()] = None,
    ) -> Response:
        """Replace the set of people on a task."""
        store.set_assignees(conn, user, task_id, assignee_ids or [])
        return Response(status_code=204, headers=TASKS_CHANGED)

    @app.post("/tasks/{task_id}/updates", status_code=204)
    def comment(conn: Conn, user: User, task_id: int, body: Annotated[str, Form()]) -> Response:
        """Post a comment on a task."""
        store.add_comment(conn, user, task_id, body)
        return Response(status_code=204, headers=TASKS_CHANGED)

    @app.post("/tasks/{task_id}/delete", status_code=204)
    def delete(conn: Conn, user: User, task_id: int) -> Response:
        """Delete a task (the UI asks for confirmation first)."""
        store.delete_task(conn, user, task_id)
        return Response(status_code=204, headers=TASKS_CHANGED)

    # ------------------------------------------------------------ notifications

    @app.get("/notifications/badge", response_class=HTMLResponse)
    def notification_badge(request: Request, conn: Conn, user: User) -> HTMLResponse:
        """The bell with its unread count; the page polls this to notice new notifications."""
        unread, newest = store.notification_counts(conn, user["id"])
        return render(request, "_notif_badge.html", unread=unread, newest=newest, user=user)

    @app.get("/notifications", response_class=HTMLResponse)
    def notification_list(request: Request, conn: Conn, user: User) -> HTMLResponse:
        """My notifications, newest first."""
        now_day = today()
        items = [
            {
                "id": n["id"],
                "task_id": n["task_id"],
                "actor": n["actor_name"] or "Someone",
                "body": n["body"],
                "title": n["title"],
                "unread": n["read_at"] is None,
                "when": dates.stamp(n["created_at"], settings.tz, now_day),
                "due": (
                    dates.due_label(date.fromisoformat(n["due_date"]), now_day)
                    if n["due_date"] and n["status"] != "done"
                    else None
                ),
            }
            for n in store.notifications_for(conn, user["id"])
        ]
        return render(request, "_notif_list.html", items=items)

    @app.post("/notifications/read-all", status_code=204)
    def notifications_read_all(conn: Conn, user: User) -> Response:
        """Mark every notification of mine as read."""
        store.set_notification_read(conn, user["id"], None, read=True)
        return Response(status_code=204, headers=NOTIFICATIONS_CHANGED)

    @app.post("/notifications/clear-read", status_code=204)
    def notifications_clear_read(conn: Conn, user: User) -> Response:
        """Delete every notification of mine that I've already read."""
        store.dismiss_notifications(conn, user["id"], None)
        return Response(status_code=204, headers=NOTIFICATIONS_CHANGED)

    @app.post("/notifications/{notification_id}/read", status_code=204)
    def notification_read(conn: Conn, user: User, notification_id: int) -> Response:
        """Mark one notification as read."""
        store.set_notification_read(conn, user["id"], notification_id, read=True)
        return Response(status_code=204, headers=NOTIFICATIONS_CHANGED)

    @app.post("/notifications/{notification_id}/unread", status_code=204)
    def notification_unread(conn: Conn, user: User, notification_id: int) -> Response:
        """Mark one notification as unread again."""
        store.set_notification_read(conn, user["id"], notification_id, read=False)
        return Response(status_code=204, headers=NOTIFICATIONS_CHANGED)

    @app.post("/notifications/{notification_id}/dismiss", status_code=204)
    def notification_dismiss(conn: Conn, user: User, notification_id: int) -> Response:
        """Delete one notification."""
        store.dismiss_notifications(conn, user["id"], notification_id)
        return Response(status_code=204, headers=NOTIFICATIONS_CHANGED)

    # ------------------------------------------------------------ people (admin)

    def people_fragment(
        request: Request, conn: Conn, me: sqlite3.Row, flash: str = ""
    ) -> HTMLResponse:
        """Render the people dialog body, telling the page that people changed."""
        response = render(
            request, "_people.html", people=store.active_people(conn), me=me, flash=flash
        )
        if flash:
            response.headers["HX-Trigger"] = "people-changed"
        return response

    @app.get("/people", response_class=HTMLResponse)
    def people(request: Request, conn: Conn, admin: Admin) -> HTMLResponse:
        """The Manage people dialog."""
        return people_fragment(request, conn, admin)

    @app.post("/people", response_class=HTMLResponse)
    def add_person(
        request: Request,
        conn: Conn,
        admin: Admin,
        name: Annotated[str, Form()],
        username: Annotated[str, Form()],
    ) -> HTMLResponse:
        """Add a person and show their one-time temporary password."""
        password = auth.temp_password()
        store.create_user(conn, name, username, password)
        flash = (
            f"Added {escape(' '.join(name.split()))}. Username: <b>{escape(username.strip().lower())}</b> · "
            f"temporary password: <code>{password}</code>. Share it with them now; it won't be "
            "shown again."
        )
        return people_fragment(request, conn, admin, Markup(flash))

    @app.post("/people/{user_id}/remove", response_class=HTMLResponse)
    def remove_person(request: Request, conn: Conn, admin: Admin, user_id: int) -> HTMLResponse:
        """Remove (deactivate) a person."""
        target = store.get_user(conn, user_id)
        store.remove_person(conn, admin, user_id)
        return people_fragment(request, conn, admin, f"Removed {target['name']}.")

    @app.post("/people/{user_id}/reset", response_class=HTMLResponse)
    def reset(request: Request, conn: Conn, admin: Admin, user_id: int) -> HTMLResponse:
        """Give a person a new temporary password."""
        target = store.get_user(conn, user_id)
        if not target or not target["is_active"]:
            raise store.UserError("That person no longer exists.")
        password = store.reset_password(conn, user_id)
        flash = Markup(
            f"New temporary password for {escape(target['name'])}: <code>{password}</code>. "
            "They'll choose their own when they next sign in."
        )
        return people_fragment(request, conn, admin, flash)

    @app.post("/people/{user_id}/admin", response_class=HTMLResponse)
    def toggle_admin(
        request: Request, conn: Conn, admin: Admin, user_id: int, make_admin: Annotated[int, Form()]
    ) -> HTMLResponse:
        """Grant or revoke admin rights."""
        store.set_admin(conn, user_id, bool(make_admin))
        target = store.get_user(conn, user_id)
        verb = "is now an admin" if make_admin else "is no longer an admin"
        return people_fragment(request, conn, admin, f"{target['name']} {verb}.")

    @app.get("/help", response_class=HTMLResponse)
    def help_page(request: Request, conn: Conn) -> HTMLResponse:
        """The user manual. Open to everyone, so it can be read before signing in."""
        found = auth.session_user(conn, request.cookies.get(auth.COOKIE_NAME))
        return render(request, "help.html", user=found[0] if found else None)

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> FileResponse:
        """The web app manifest that lets phones install the app to the home screen."""
        return FileResponse(
            HERE / "static" / "manifest.webmanifest", media_type="application/manifest+json"
        )

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        """The service worker that shows desktop alerts; served from the root so it covers the site."""
        return FileResponse(
            HERE / "static" / "sw.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz(conn: Conn) -> str:
        """Liveness check that also touches the database."""
        conn.execute("SELECT 1").fetchone()
        return "ok"

    return app
