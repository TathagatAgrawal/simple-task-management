"""Tests for passwords, sessions, CSRF and the sign-in flow."""

import pytest
from conftest import PASSWORD, sign_in
from fastapi.testclient import TestClient

from simple_task_management import auth, store


def test_password_hash_roundtrip():
    """A hash verifies its own password and nothing else."""
    stored = auth.hash_password("s3cret-pass")
    assert stored.startswith("scrypt$")
    assert auth.verify_password("s3cret-pass", stored)
    assert not auth.verify_password("wrong", stored)
    assert not auth.verify_password("s3cret-pass", "garbage")


def test_temp_password_is_readable():
    """Temporary passwords avoid look-alike characters."""
    pw = auth.temp_password()
    assert len(pw) == 11 and pw[5] == "-"
    assert not set(pw) & set("0o1li")


def test_the_page_is_a_shell_for_the_client(app, users):
    """The page is a small shell that loads the built client, whether or not you're signed in."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert '<div id="root">' in page
    assert "/static/dist/app.js" in page
    assert "htmx" not in page


def test_username_is_case_insensitive(app, users):
    """People can type their username with capitals."""
    client = sign_in(app, "ASHA")
    assert client.get("/api/me").json()["name"] == "Asha Iyer"


def test_sign_in_must_be_json(app, users):
    """A plain cross-site form post cannot sign anyone in: the endpoint only accepts JSON."""
    with TestClient(app) as client:
        r = client.post("/api/session", data={"username": "asha", "password": PASSWORD})
    assert r.status_code == 422


def test_board_requires_a_session(app, users):
    """Without a session the API answers 401 as JSON, never a redirect."""
    with TestClient(app) as client:
        r = client.get("/api/board", follow_redirects=False)
    assert r.status_code == 401 and r.json() == {"error": "Sign in required."}


def test_post_without_csrf_is_rejected(asha):
    """A write missing the CSRF header fails even with a valid cookie."""
    r = asha.post(
        "/api/tasks",
        json={"title": "x", "due": "2026-11-20"},
        headers={"X-CSRF-Token": ""},
    )
    assert r.status_code == 403


def test_logout(asha):
    """Signing out ends the session."""
    assert asha.delete("/api/session").status_code == 204
    assert asha.get("/api/board").status_code == 401


def test_temporary_password_forces_change(app, conn, users):
    """Someone with a temporary password must choose their own before using the app."""
    temp = store.reset_password(conn, users["ravi"])
    client = sign_in(app, "ravi", temp)
    assert client.get("/api/me").json()["must_change_password"] is True
    assert client.get("/api/board").status_code == 403

    r = client.post(
        "/api/me/password",
        json={"new_password": "brand-new-pass", "confirm_password": "brand-new-pass"},
    )
    assert r.status_code == 204
    assert client.get("/api/board").status_code == 200


def test_change_password_needs_current(asha):
    """Voluntary password changes check the current password and the confirmation."""
    data = {"new_password": "another-pass", "confirm_password": "another-pass"}
    r = asha.post("/api/me/password", json=data | {"current_password": "wrong"})
    assert r.status_code == 400
    r = asha.post(
        "/api/me/password", json=data | {"current_password": PASSWORD, "confirm_password": "x"}
    )
    assert r.status_code == 400 and "match" in r.json()["error"]
    r = asha.post("/api/me/password", json=data | {"current_password": PASSWORD})
    assert r.status_code == 204


def test_short_passwords_rejected(conn, users):
    """Passwords under the minimum length are refused."""
    with pytest.raises(store.UserError):
        store.set_password(conn, users["ravi"], "short")


def test_healthz(app):
    """The health check responds without signing in."""
    with TestClient(app) as client:
        assert client.get("/healthz").text == "ok"
