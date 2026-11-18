"""FastAPI application: the page shell, the user manual, and the JSON API under ``/api``.

``GET /`` serves a small HTML shell that loads the TypeScript client (built into
``static/dist/app.js``); the client does everything else through the API in ``api.py``. The
user manual (``/help``) is the one page that is still rendered on the server.
"""

import asyncio
import contextlib
import hashlib
import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, backup, dates, db, events, push, updates
from .api import build_api
from .config import Settings, load_settings

HERE = Path(__file__).parent


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
    """Jinja environment with the cache-busting ``version`` global."""
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals["version"] = static_fingerprint()
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
    hub = events.Hub()
    checker = updates.Checker()
    pusher = push.Pusher(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Migrate the database on startup and run the nightly backup in the background."""
        conn = db.connect(settings.db_path)
        db.migrate(conn)
        conn.close()
        tasks = []
        if settings.backups_enabled:
            tasks.append(asyncio.create_task(backup.nightly_loop(settings)))
        if settings.update_check_enabled:
            tasks.append(asyncio.create_task(checker.loop(settings.update_check_hours, hub)))
        if settings.push_enabled:
            tasks.append(asyncio.create_task(pusher.loop(hub)))
        yield
        hub.close()
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.hub = hub  # tests subscribe to it to watch what gets announced
    app.state.pusher = pusher  # tests give it a recording sender instead of the real one
    app.state.checker = checker  # tests replace its answer instead of reaching for GitHub
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def today() -> date:
        """The firm's current calendar date."""
        return dates.today_in(settings.tz, clock())

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
        build_api(
            settings=settings,
            today=today,
            get_conn=get_conn,
            throttle=throttle,
            hub=hub,
            checker=checker,
            pusher=pusher,
        ),
    )

    def signed_in_user(request: Request, conn: sqlite3.Connection) -> sqlite3.Row | None:
        """Whoever the session cookie belongs to, if anyone (used only to pick the theme)."""
        found = auth.session_user(conn, request.cookies.get(auth.COOKIE_NAME))
        return found[0] if found else None

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, conn: Conn) -> HTMLResponse:
        """The page shell. The TypeScript client takes over from here and calls ``/api``."""
        return templates.TemplateResponse(
            request, "index.html", {"user": signed_in_user(request, conn)}
        )

    @app.get("/help", response_class=HTMLResponse)
    def help_page(request: Request, conn: Conn) -> HTMLResponse:
        """The user manual. Open to everyone, so it can be read before signing in."""
        return templates.TemplateResponse(
            request, "help.html", {"user": signed_in_user(request, conn)}
        )

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
