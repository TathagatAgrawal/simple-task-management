"""Shared fixtures: an isolated app per test, a fixed clock, and signed-in clients."""

import re
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from simple_task_management import db, store
from simple_task_management.app import create_app
from simple_task_management.config import Settings

# 10:00 IST on Saturday 14 Nov 2026.
NOW = datetime(2026, 11, 14, 4, 30, tzinfo=UTC)
TODAY = date(2026, 11, 14)
PASSWORD = "correct-horse"


@pytest.fixture
def settings(tmp_path):
    """Settings pointing at a temporary data directory, with backups off."""
    return Settings(
        data_dir=tmp_path / "data",
        backup_dir=tmp_path / "backups",
        log_dir=tmp_path / "logs",
        backups_enabled=False,
    )


@pytest.fixture
def conn(settings):
    """A migrated connection to the test database."""
    connection = db.connect(settings.db_path)
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def users(conn):
    """Three people: an admin (asha) and two members (ravi, meera)."""
    return {
        "asha": store.create_user(
            conn, "Asha Iyer", "asha", PASSWORD, is_admin=True, must_change_password=False
        ),
        "ravi": store.create_user(conn, "Ravi Kumar", "ravi", PASSWORD, must_change_password=False),
        "meera": store.create_user(
            conn, "Meera Shah", "meera", PASSWORD, must_change_password=False
        ),
    }


@pytest.fixture
def app(settings, conn):
    """The FastAPI app with a fixed clock."""
    return create_app(settings, clock=lambda: NOW)


def sign_in(app, username: str, password: str = PASSWORD) -> TestClient:
    """Return a client signed in as ``username`` that sends the CSRF header like htmx does."""
    client = TestClient(app)
    client.__enter__()
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        headers={"HX-Request": "true"},
    )
    assert response.headers.get("HX-Redirect") == "/", response.text
    page = client.get("/").text
    match = re.search(r'"X-CSRF-Token": "([^"]*)"', page)
    assert match
    client.headers.update({"X-CSRF-Token": match.group(1), "HX-Request": "true"})
    return client


@pytest.fixture
def asha(app, users):
    """Client signed in as the admin."""
    client = sign_in(app, "asha")
    yield client
    client.__exit__(None, None, None)


@pytest.fixture
def ravi(app, users):
    """Client signed in as a non-admin."""
    client = sign_in(app, "ravi")
    yield client
    client.__exit__(None, None, None)


def new_task(client: TestClient, **fields) -> None:
    """Create a task through the HTTP API, asserting success."""
    data = {"title": "A task", "due": TODAY.isoformat(), "repeat": "none"} | fields
    response = client.post("/tasks", data=data)
    assert response.status_code == 204, response.text
