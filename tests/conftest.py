"""Shared fixtures: an isolated app per test, a fixed clock, and signed-in clients."""

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
    """Settings pointing at a temporary data directory, with backups and background pushing off."""
    return Settings(
        data_dir=tmp_path / "data",
        backup_dir=tmp_path / "backups",
        log_dir=tmp_path / "logs",
        backups_enabled=False,
        push_enabled=False,
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
    """Return a client signed in as ``username`` the way the web page does it.

    The session cookie comes from ``POST /api/session``, and every request carries the CSRF header.
    """
    client = TestClient(app)
    client.__enter__()
    response = client.post("/api/session", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["user"]["csrf_token"]
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


def new_task(client: TestClient, **fields) -> int:
    """Create a task through the JSON API, asserting success; returns its id."""
    data = {"title": "A task", "due": TODAY.isoformat(), "repeat": "none"} | fields
    response = client.post("/api/tasks", json=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def move(client: TestClient, task_id: int, status: str):
    """Move a task to another column through the JSON API and return the response."""
    return client.patch(f"/api/tasks/{task_id}", json={"status": status})


def board(client: TestClient, who: str = "all", **params):
    """The board as JSON (``{"todo": [...], ...}``)."""
    response = client.get("/api/board", params={"who": who, **params})
    assert response.status_code == 200, response.text
    return response.json()


def board_titles(client: TestClient, who: str = "all", **params) -> set[str]:
    """Titles of every card on the board."""
    return {card["title"] for cards in board(client, who, **params).values() for card in cards}
