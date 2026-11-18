"""The JSON API, mounted at ``/api``.

A second front door to the same data: it calls the same ``store.py`` functions as the HTML routes
(so every rule and every history event still lives in one place) and returns JSON instead of HTML
fragments. Any client can use it: a different web UI, a phone app, a script.

Sign in with ``POST /api/session`` and send the returned token as ``Authorization: Bearer <token>``.
The browser cookie also works; unsafe requests made with the cookie must carry the ``X-CSRF-Token``
header (``GET /api/me`` returns it). Errors are always ``{"error": "message"}``.
"""

import hmac
import sqlite3
from collections.abc import Callable, Iterator
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, dates, events, push, schemas, store, updates
from .config import Settings
from .recurrence import REPEAT_LABELS

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
OTHERS_OVERDUE_SHOWN = 3  # how many hidden overdue tasks the strip names


class Body(BaseModel):
    """Base for request bodies: unknown fields are rejected so typos don't pass silently."""

    model_config = ConfigDict(extra="forbid")


class LoginIn(Body):
    """Credentials for ``POST /api/session``."""

    username: str
    password: str


class MeIn(Body):
    """Changes to your own settings."""

    theme: str


class PasswordIn(Body):
    """A password change; ``current_password`` is not needed while the password is temporary."""

    current_password: str = ""
    new_password: str
    confirm_password: str


class TaskIn(Body):
    """A new task."""

    title: str
    due: str
    notes: str = ""
    repeat: str = "none"
    assignee_ids: list[int] = []


class TaskPatch(Body):
    """Any subset of a task's fields; fields left out are not changed."""

    title: str | None = None
    notes: str | None = None
    due: str | None = None
    repeat: str | None = None
    status: str | None = None
    assignee_ids: list[int] | None = None


class UpdateIn(Body):
    """A comment on a task."""

    body: str


class PersonIn(Body):
    """A person to add."""

    name: str
    username: str


class UpdatePatch(Body):
    """Turn automatic nightly updates on or off."""

    auto_update: bool


class PersonPatch(Body):
    """Change a person's admin flag."""

    is_admin: bool


def person_json(row: sqlite3.Row) -> dict:
    """A person as other people see them."""
    return {
        "id": row["id"],
        "name": row["name"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
    }


def assignees_json(rows: list[sqlite3.Row]) -> list[dict]:
    """Assignees as ``{id, name}`` pairs."""
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def card_json(card: dict) -> dict:
    """A board card from ``store.board``, with its date as ISO text."""
    return {
        "id": card["id"],
        "title": card["title"],
        "status": card["status"],
        "due": card["due"].isoformat(),
        "due_label": card["due_label"],
        "due_tone": card["due_tone"],
        "repeat": card["repeat"],
        "repeat_label": card["repeat_label"],
        "assignees": assignees_json(card["assignees"]),
        "comments": card["comments"],
    }


def build_api(
    *,
    settings: Settings,
    today: Callable[[], date],
    get_conn: Callable[[], Iterator[sqlite3.Connection]],
    throttle: auth.LoginThrottle,
    hub: events.Hub,
    checker: updates.Checker,
    pusher: push.Pusher,
) -> FastAPI:
    """Build the JSON API app. ``create_app`` mounts it at ``/api`` and shares its helpers."""
    api = FastAPI(
        title="Simple Task Management API",
        description=__doc__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def changed(*topics: str) -> None:
        """Tell every open page that something changed, so it refreshes at once."""
        hub.publish(*topics)

    # ------------------------------------------------------------ errors

    @api.exception_handler(store.UserError)
    async def user_error(request: Request, exc: store.UserError) -> JSONResponse:
        """A problem with the input, in the person's own words."""
        return JSONResponse({"error": str(exc)}, status_code=400)

    @api.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Every HTTP error is ``{"error": ...}``, never a redirect or HTML."""
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @api.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Malformed or missing fields."""
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"] if p != "body")
        return JSONResponse({"error": f"{field}: {first['msg']}".strip(": ")}, status_code=422)

    # ------------------------------------------------------------ authentication

    def bearer_token(request: Request) -> str | None:
        """The token from an ``Authorization: Bearer`` header, if there is one."""
        header = request.headers.get("Authorization", "")
        return header[7:].strip() if header.lower().startswith("bearer ") else None

    def signed_in(request: Request, conn: Conn) -> sqlite3.Row:
        """Whoever the token or cookie belongs to, even if they must still pick a password."""
        token = bearer_token(request)
        found = auth.session_user(conn, token or request.cookies.get(auth.COOKIE_NAME))
        if not found:
            raise HTTPException(401, "Sign in required.")
        user, csrf = found
        if (
            token is None
            and request.method not in SAFE_METHODS
            and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), csrf)
        ):
            raise HTTPException(403, "Missing or wrong X-CSRF-Token.")
        return user

    Signed = Annotated[sqlite3.Row, Depends(signed_in)]

    def active_user(user: Signed) -> sqlite3.Row:
        """The signed-in user, who must have chosen their own password already."""
        if user["must_change_password"]:
            raise HTTPException(403, "Choose a new password first (POST /api/me/password).")
        return user

    User = Annotated[sqlite3.Row, Depends(active_user)]

    def admin_user(user: User) -> sqlite3.Row:
        """The signed-in user, who must be an admin."""
        if not user["is_admin"]:
            raise HTTPException(403, "Only admins can manage people.")
        return user

    Admin = Annotated[sqlite3.Row, Depends(admin_user)]

    def me_json(user: sqlite3.Row) -> dict:
        """The signed-in user, with their settings and the CSRF token for cookie clients."""
        return {
            **person_json(user),
            "theme": user["theme"],
            "must_change_password": bool(user["must_change_password"]),
            "csrf_token": user["csrf_token"],
        }

    @api.post("/session", tags=["session"], response_model=schemas.Session)
    def sign_in(request: Request, response: Response, conn: Conn, body: LoginIn) -> dict:
        """Check credentials and start a 30-day session. Returns the bearer token."""
        throttle.wait(body.username)
        user = store.user_by_username(conn, body.username)
        if not user or not auth.verify_password(body.password, user["password_hash"]):
            throttle.failed(body.username)
            raise HTTPException(401, "Wrong username or password.")
        throttle.succeeded(body.username)
        token = auth.create_session(conn, user["id"])
        auth.set_session_cookie(response, request, token)
        found = auth.session_user(conn, token)
        return {"token": token, "user": me_json(found[0])}

    @api.delete("/session", status_code=204, tags=["session"])
    def sign_out(request: Request, conn: Conn, user: Signed) -> Response:
        """End the session this request used."""
        auth.end_session(conn, bearer_token(request) or request.cookies.get(auth.COOKIE_NAME))
        response = Response(status_code=204)
        response.delete_cookie(auth.COOKIE_NAME)
        return response

    @api.get("/me", tags=["me"], response_model=schemas.Me)
    def me(user: Signed) -> dict:
        """The signed-in user."""
        return me_json(user)

    @api.patch("/me", tags=["me"], response_model=schemas.Me)
    def update_me(conn: Conn, user: User, body: MeIn) -> dict:
        """Change your theme (``system``, ``light`` or ``dark``)."""
        store.set_theme(conn, user["id"], body.theme)
        return {**me_json(user), "theme": body.theme}

    @api.post("/me/password", status_code=204, tags=["me"])
    def change_password(conn: Conn, user: Signed, body: PasswordIn) -> Response:
        """Set a new password; the current one is required unless it was temporary."""
        if not user["must_change_password"] and not auth.verify_password(
            body.current_password, user["password_hash"]
        ):
            raise store.UserError("Your current password is not right.")
        if body.new_password != body.confirm_password:
            raise store.UserError("The two new passwords don't match.")
        store.set_password(conn, user["id"], body.new_password)
        return Response(status_code=204)

    @api.get("/meta", tags=["me"], response_model=schemas.Meta)
    def meta(user: User) -> dict:
        """Labels and choices the page needs, and the firm's date today."""
        return {
            "today": today(),
            "statuses": [{"value": v, "label": lbl} for v, lbl in store.STATUS_LABELS.items()],
            "repeats": [{"value": v, "label": lbl} for v, lbl in REPEAT_LABELS.items()],
            "notification_kinds": [
                {"kind": k, "label": lbl, "help": hlp}
                for k, (lbl, hlp) in store.NOTIFICATION_KINDS.items()
            ],
            "notification_modes": [
                {"value": v, "label": lbl} for v, lbl in store.NOTIFICATION_MODES.items()
            ],
        }

    @api.get("/events", tags=["live"], response_class=StreamingResponse)
    async def live_events(user: User) -> StreamingResponse:
        """A Server-Sent Events stream: ``data: ["tasks", ...]`` whenever those topics change.

        Topics are ``tasks``, ``notifications`` and ``people``; the first message is ``["ready"]``.
        A page refetches what it shows for each topic. Comment lines (``: ping``) keep it alive.
        """
        return StreamingResponse(
            events.stream(hub),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------ board and tasks

    def task_json(conn: sqlite3.Connection, task: sqlite3.Row) -> dict:
        """One task with its assignees, its updates and the rest of its recurring series."""
        now_day = today()
        due = date.fromisoformat(task["due_date"])
        label, tone = dates.due_label(due, now_day)
        updates = store.thread(conn, task["id"])
        return {
            "id": task["id"],
            "title": task["title"],
            "notes": task["notes"],
            "status": task["status"],
            "due": task["due_date"],
            "due_label": label if task["status"] != "done" else "",
            "due_tone": tone,
            "repeat": task["repeat"],
            "repeat_label": REPEAT_LABELS[task["repeat"]],
            "done_at": task["done_at"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
            "assignees": assignees_json(store.assignees_for(conn, [task["id"]])[task["id"]]),
            "updates": [
                {
                    "id": u["update_id"],
                    "kind": u["kind"],
                    "body": u["body"],
                    "author": {"id": u["author_id"], "name": u["author_name"]}
                    if u["author_id"]
                    else None,
                    "created_at": u["created_at"],
                    "when": dates.stamp(u["created_at"], settings.tz, now_day),
                }
                for u in updates
            ],
            "series": [
                {
                    "id": s["id"],
                    "due": s["due_date"],
                    "due_short": dates.short_date(date.fromisoformat(s["due_date"]), now_day),
                    "status": s["status"],
                }
                for s in store.series(conn, task)
            ],
        }

    def existing_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
        """The task row, or a 404."""
        task = store.get_task(conn, task_id)
        if task is None:
            raise HTTPException(404, "That task doesn't exist.")
        return task

    def others_overdue(
        conn: sqlite3.Connection, everyone: list[dict], shown: list[dict], now_day: date
    ) -> list[dict]:
        """The firm's overdue tasks that the current filter hides (the first few), with their people."""
        shown_ids = {t["id"] for t in shown}
        hidden = [t for t in everyone if t["id"] not in shown_ids][:OTHERS_OVERDUE_SHOWN]
        people = store.assignees_for(conn, [t["id"] for t in hidden])
        return [
            {
                "id": t["id"],
                "title": t["title"],
                "due_label": dates.due_label(t["due"], now_day)[0],
                "people": ", ".join(p["name"].split()[0] for p in people[t["id"]]) or "Unassigned",
            }
            for t in hidden
        ]

    @api.get("/summary", tags=["board"], response_model=schemas.Summary)
    def summary(conn: Conn, user: User, who: str = "me") -> dict:
        """Open tasks that are overdue, due today, or due in the next three days.

        ``who`` is ``me``, ``all``, ``none`` (unassigned) or a person's id.
        """
        now_day = today()
        buckets = store.summary(conn, who=who, me=user["id"], today=now_day)
        everyone = store.summary(conn, who="all", me=user["id"], today=now_day)
        return {
            **{
                key: [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "due": t["due"].isoformat(),
                        "due_label": dates.due_label(t["due"], now_day)[0],
                        "due_tone": dates.due_label(t["due"], now_day)[1],
                        "repeat": t["repeat"],
                    }
                    for t in tasks
                ]
                for key, tasks in buckets.items()
            },
            # Overdue work across the whole firm, so "My tasks" can never hide it.
            "firm_overdue": len(everyone["overdue"]),
            "others_overdue": others_overdue(
                conn, everyone["overdue"], buckets["overdue"], now_day
            ),
        }

    @api.get("/board", tags=["board"], response_model=schemas.Board)
    def board(conn: Conn, user: User, who: str = "me", done_days: int = 14) -> dict:
        """The three columns of cards: ``todo``, ``doing`` and ``done`` (last ``done_days`` days)."""
        columns = store.board(
            conn, who=who, me=user["id"], today=today(), tz=settings.tz, done_days=done_days
        )
        return {status: [card_json(c) for c in cards] for status, cards in columns.items()}

    @api.post("/tasks", status_code=201, tags=["tasks"], response_model=schemas.Task)
    def create_task(conn: Conn, user: User, body: TaskIn) -> dict:
        """Create a task."""
        task_id = store.create_task(
            conn,
            user,
            title=body.title,
            due=body.due,
            notes=body.notes,
            repeat=body.repeat,
            assignee_ids=body.assignee_ids,
        )
        changed("tasks", "notifications")
        return task_json(conn, store.get_task(conn, task_id))

    @api.get("/tasks/{task_id}", tags=["tasks"], response_model=schemas.Task)
    def get_task(conn: Conn, user: User, task_id: int) -> dict:
        """One task with its updates."""
        return task_json(conn, existing_task(conn, task_id))

    @api.patch("/tasks/{task_id}", tags=["tasks"], response_model=schemas.TaskPatched)
    def patch_task(conn: Conn, user: User, task_id: int, body: TaskPatch) -> dict:
        """Change any of title, notes, due, repeat, status and assignees.

        Every real change is logged in the task's updates. Moving a recurring task to ``done``
        creates the next occurrence; its id is returned as ``next_task_id``.
        """
        existing_task(conn, task_id)
        changes = body.model_dump(exclude_unset=True)
        # Check everything first, so a bad value can't leave the task half-changed.
        if "title" in changes:
            store.clean_title(changes["title"] or "")
        if "notes" in changes:
            store.clean_text(changes["notes"] or "", "Notes")
        if "due" in changes:
            store.parse_due(changes["due"] or "")
        if "repeat" in changes:
            store.check_repeat(changes["repeat"] or "")
        if "status" in changes:
            store.check_status(changes["status"] or "")
        if changes.get("assignee_ids") is not None:
            store.set_assignees(conn, user, task_id, changes["assignee_ids"])
        store.update_task(
            conn,
            user,
            task_id,
            title=changes.get("title"),
            notes=changes.get("notes"),
            due=changes.get("due"),
            repeat=changes.get("repeat"),
            today=today(),
        )
        next_id = None
        if changes.get("status") is not None:
            next_id = store.move_task(conn, user, task_id, changes["status"], today())
        changed("tasks", "notifications")
        return {**task_json(conn, store.get_task(conn, task_id)), "next_task_id": next_id}

    @api.delete("/tasks/{task_id}", status_code=204, tags=["tasks"])
    def delete_task(conn: Conn, user: User, task_id: int) -> Response:
        """Delete a task and all its updates, for good."""
        existing_task(conn, task_id)
        store.delete_task(conn, user, task_id)
        changed("tasks", "notifications")
        return Response(status_code=204)

    @api.post(
        "/tasks/{task_id}/updates", status_code=201, tags=["tasks"], response_model=schemas.Task
    )
    def add_update(conn: Conn, user: User, task_id: int, body: UpdateIn) -> dict:
        """Post a comment. Returns the task with its refreshed updates."""
        existing_task(conn, task_id)
        store.add_comment(conn, user, task_id, body.body)
        changed("tasks", "notifications")
        return task_json(conn, store.get_task(conn, task_id))

    # ------------------------------------------------------------ notifications

    def notification_json(n: sqlite3.Row) -> dict:
        """One notification, with ready-made ``text`` and ``detail`` lines for showing it."""
        now_day = today()
        actor = n["actor_name"] or "Someone"
        label, tone = (
            dates.due_label(date.fromisoformat(n["due_date"]), now_day)
            if n["due_date"] and n["status"] != "done"
            else (None, "")
        )
        return {
            "id": n["id"],
            "task_id": n["task_id"],
            "kind": n["kind"],
            "actor": actor,
            "body": n["body"],
            "title": n["title"],
            "text": f"{actor} {n['body']}",
            "detail": n["title"],
            "read": n["read_at"] is not None,
            "announce": bool(n["announce"]),
            # Deadline and assignment changes stay on screen until dismissed; the rest fade.
            "sticky": store.is_sticky(n["kind"], n["body"]),
            "created_at": n["created_at"],
            "when": dates.stamp(n["created_at"], settings.tz, now_day),
            "due_label": label,
            "due_tone": tone,
        }

    @api.get("/notifications", tags=["notifications"], response_model=list[schemas.Notification])
    def notifications(
        conn: Conn, user: User, after: int = 0, unread: bool = False, announce: bool = False
    ) -> list[dict]:
        """My notifications, newest first (at most 50). ``after`` is a notification id.

        ``announce`` leaves out the "inbox only" ones (see the notification settings).
        """
        found = store.notifications_for(
            conn, user["id"], after=after, unread_only=unread, announce_only=announce
        )
        return [notification_json(n) for n in found]

    @api.get(
        "/me/notification-settings",
        tags=["notifications"],
        response_model=dict[str, schemas.Mode],
    )
    def get_notification_settings(conn: Conn, user: User) -> dict:
        """What I get notified about: ``{kind: "alert" | "inbox" | "off"}`` for every kind."""
        return store.notification_settings(conn, user["id"])

    @api.patch(
        "/me/notification-settings",
        tags=["notifications"],
        response_model=dict[str, schemas.Mode],
    )
    def patch_notification_settings(conn: Conn, user: User, body: dict[str, str]) -> dict:
        """Change some of my settings, e.g. ``{"comment": "inbox", "moved": "off"}``."""
        store.set_notification_settings(conn, user["id"], body)
        return store.notification_settings(conn, user["id"])

    @api.get("/notifications/unread", tags=["notifications"], response_model=schemas.Unread)
    def notifications_unread(conn: Conn, user: User) -> dict:
        """How many are unread, and the id of the newest one."""
        unread, newest = store.notification_counts(conn, user["id"])
        return {"unread": unread, "newest": newest}

    @api.post("/notifications/read-all", status_code=204, tags=["notifications"])
    def notifications_read_all(conn: Conn, user: User) -> Response:
        """Mark all my notifications as read."""
        store.set_notification_read(conn, user["id"], None, read=True)
        changed("notifications")
        return Response(status_code=204)

    @api.post("/notifications/{notification_id}/read", status_code=204, tags=["notifications"])
    def notification_read(conn: Conn, user: User, notification_id: int) -> Response:
        """Mark one notification as read."""
        store.set_notification_read(conn, user["id"], notification_id, read=True)
        changed("notifications")
        return Response(status_code=204)

    @api.post("/notifications/{notification_id}/unread", status_code=204, tags=["notifications"])
    def notification_unread(conn: Conn, user: User, notification_id: int) -> Response:
        """Mark one notification as unread."""
        store.set_notification_read(conn, user["id"], notification_id, read=False)
        changed("notifications")
        return Response(status_code=204)

    @api.delete("/notifications/{notification_id}", status_code=204, tags=["notifications"])
    def notification_dismiss(conn: Conn, user: User, notification_id: int) -> Response:
        """Delete one notification."""
        store.dismiss_notifications(conn, user["id"], notification_id)
        changed("notifications")
        return Response(status_code=204)

    @api.delete("/notifications", status_code=204, tags=["notifications"])
    def notifications_clear_read(conn: Conn, user: User) -> Response:
        """Delete every notification I've already read."""
        store.dismiss_notifications(conn, user["id"], None)
        changed("notifications")
        return Response(status_code=204)

    # ------------------------------------------------------------ push (alerts on a device)

    def push_info(conn: sqlite3.Connection, user: sqlite3.Row, endpoint: str = "") -> dict:
        """What the page needs to set up alerts on this device."""
        return {
            "enabled": settings.push_enabled,
            "public_key": push.public_key(conn) if settings.push_enabled else "",
            "details": store.push_details(conn, user["id"]),
            "devices": len(store.push_subscriptions_for(conn, user["id"])),
            "this_device": bool(endpoint)
            and store.has_push_subscription(conn, user["id"], endpoint),
        }

    @api.get("/push", tags=["push"], response_model=schemas.PushInfo)
    def get_push(conn: Conn, user: User, endpoint: str = "") -> dict:
        """The key a browser needs to subscribe, my banner choice, and whether ``endpoint`` is saved."""
        return push_info(conn, user, endpoint)

    @api.patch("/push", tags=["push"], response_model=schemas.PushInfo)
    def patch_push(conn: Conn, user: User, body: schemas.PushPatch) -> dict:
        """Choose whether my banners show the task's title or only "a task changed"."""
        store.set_push_details(conn, user["id"], body.details)
        return push_info(conn, user)

    @api.put("/push/subscription", status_code=204, tags=["push"])
    def put_push_subscription(conn: Conn, user: User, body: schemas.PushSubscriptionIn) -> Response:
        """Save this device so it receives alerts. Saving the same device again is harmless."""
        store.save_push_subscription(
            conn, user["id"], body.endpoint, body.keys.p256dh, body.keys.auth
        )
        return Response(status_code=204)

    @api.post("/push/unsubscribe", status_code=204, tags=["push"])
    def unsubscribe_push(conn: Conn, user: User, body: schemas.PushEndpointIn) -> Response:
        """Stop alerts on this device. Only my own devices can be removed."""
        store.delete_push_subscription(conn, body.endpoint, user["id"])
        return Response(status_code=204)

    @api.post("/push/test", tags=["push"], response_model=schemas.PushTestResult)
    def test_push(conn: Conn, user: User) -> dict:
        """Send a sample alert to all of my devices."""
        if not settings.push_enabled:
            raise store.UserError("Alerts when the board is closed are turned off on this server.")
        if not store.push_subscriptions_for(conn, user["id"]):
            raise store.UserError("None of your devices has alerts turned on yet.")
        return {"sent": pusher.send_test(conn, user["id"])}

    # ------------------------------------------------------------ updates (admin)

    def update_info(conn: sqlite3.Connection) -> dict:
        """What the last look at GitHub found, plus the auto-update setting and last nightly run."""
        now_day = today()
        status = checker.status or updates.Status(supported=(checker.app_dir / ".git").exists())
        last = updates.read_last_run(settings.data_dir)
        last_run = None
        if last:
            try:
                when = dates.stamp(str(last["ran_at"]), settings.tz, now_day)
            except ValueError:
                when = str(last["ran_at"])
            last_run = {
                "ran_at": str(last["ran_at"]),
                "when": when,
                "result": str(last["result"]),
                "detail": str(last.get("detail", "")),
            }
        return {
            "supported": status.supported,
            "available": status.behind > 0,
            "behind": status.behind,
            "current": status.current,
            "latest": status.latest,
            "commits": status.commits,
            "checked_at": status.checked_at,
            "checked_when": (
                dates.stamp(status.checked_at, settings.tz, now_day) if status.checked_at else None
            ),
            "error": status.error,
            "auto_update": store.get_setting(conn, "auto_update", "off") == "on",
            "last_run": last_run,
        }

    @api.get("/update", tags=["updates"], response_model=schemas.UpdateInfo)
    def get_update(conn: Conn, admin: Admin) -> dict:
        """Is a newer version waiting on GitHub? (Admins only.) Installing it is done on the PC."""
        return update_info(conn)

    @api.post("/update/check", tags=["updates"], response_model=schemas.UpdateInfo)
    def check_update(conn: Conn, admin: Admin) -> dict:
        """Look at GitHub right now (takes a few seconds). Admins only."""
        checker.check_now()
        changed("updates")
        return update_info(conn)

    @api.patch("/update", tags=["updates"], response_model=schemas.UpdateInfo)
    def patch_update(conn: Conn, admin: Admin, body: UpdatePatch) -> dict:
        """Turn automatic nightly updates on or off. Admins only; the PC's nightly task does the work."""
        store.set_setting(conn, "auto_update", "on" if body.auto_update else "off")
        changed("updates")
        return update_info(conn)

    # ------------------------------------------------------------ people

    @api.get("/people", tags=["people"], response_model=list[schemas.Person])
    def people(conn: Conn, user: User) -> list[dict]:
        """Everyone who can sign in, alphabetically."""
        return [person_json(p) for p in store.active_people(conn)]

    @api.post("/people", status_code=201, tags=["people"], response_model=schemas.PersonCreated)
    def add_person(conn: Conn, admin: Admin, body: PersonIn) -> dict:
        """Add a person (admins only). The temporary password is shown only in this response."""
        password = auth.temp_password()
        user_id = store.create_user(conn, body.name, body.username, password)
        changed("people")
        return {
            "person": person_json(store.get_user(conn, user_id)),
            "temporary_password": password,
        }

    @api.patch("/people/{user_id}", tags=["people"], response_model=schemas.Person)
    def update_person(conn: Conn, admin: Admin, user_id: int, body: PersonPatch) -> dict:
        """Grant or revoke admin rights (admins only)."""
        if store.get_user(conn, user_id) is None:
            raise HTTPException(404, "That person doesn't exist.")
        store.set_admin(conn, user_id, body.is_admin)
        changed("people")
        return person_json(store.get_user(conn, user_id))

    @api.post(
        "/people/{user_id}/reset-password",
        tags=["people"],
        response_model=schemas.TemporaryPassword,
    )
    def reset_password(conn: Conn, admin: Admin, user_id: int) -> dict:
        """Give a person a new temporary password and sign them out everywhere (admins only)."""
        target = store.get_user(conn, user_id)
        if not target or not target["is_active"]:
            raise HTTPException(404, "That person doesn't exist.")
        return {"temporary_password": store.reset_password(conn, user_id)}

    @api.delete("/people/{user_id}", status_code=204, tags=["people"])
    def remove_person(conn: Conn, admin: Admin, user_id: int) -> Response:
        """Remove a person: they can't sign in and are taken off open tasks (admins only)."""
        if store.get_user(conn, user_id) is None:
            raise HTTPException(404, "That person doesn't exist.")
        store.remove_person(conn, admin, user_id)
        changed("people", "tasks")
        return Response(status_code=204)

    return api
