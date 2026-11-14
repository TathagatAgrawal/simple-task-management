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


def test_signed_out_page_shows_login(app, users):
    """Without a session the page is the login form."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert 'hx-post="/login"' in page


def test_wrong_password(app, users):
    """A bad password returns the error message and no session cookie."""
    with TestClient(app) as client:
        r = client.post(
            "/login", data={"username": "asha", "password": "nope"}, headers={"HX-Request": "true"}
        )
    assert "Wrong username or password" in r.text
    assert auth.COOKIE_NAME not in r.cookies


def test_login_requires_htmx_header(app, users):
    """Plain cross-site form posts to /login are refused."""
    with TestClient(app) as client:
        r = client.post("/login", data={"username": "asha", "password": PASSWORD})
    assert r.status_code == 400


def test_username_is_case_insensitive(app, users):
    """People can type their username with capitals."""
    client = sign_in(app, "ASHA")
    assert "Asha Iyer" in client.get("/").text


def test_fragments_require_session(app, users):
    """Htmx requests without a session are redirected to the login page."""
    with TestClient(app) as client:
        r = client.get("/board", headers={"HX-Request": "true"})
        assert r.status_code == 401 and r.headers["HX-Redirect"] == "/"
        r = client.get("/board", follow_redirects=False)
        assert r.status_code == 303


def test_post_without_csrf_is_rejected(asha):
    """A POST missing the CSRF header fails even with a valid cookie."""
    r = asha.post("/tasks", data={"title": "x", "due": "2026-11-20"}, headers={"X-CSRF-Token": ""})
    assert r.status_code == 403


def test_logout(asha):
    """Signing out ends the session."""
    assert asha.post("/logout").headers["HX-Redirect"] == "/"
    assert asha.get("/board").status_code == 401


def test_temporary_password_forces_change(app, conn, users):
    """Someone with a temporary password must choose their own before using the app."""
    temp = store.reset_password(conn, users["ravi"])
    client = sign_in(app, "ravi", temp)
    assert "choose your own password" in client.get("/").text
    assert client.get("/board").status_code == 401

    r = client.post(
        "/me/password",
        data={"new_password": "brand-new-pass", "confirm_password": "brand-new-pass"},
    )
    assert r.headers["HX-Redirect"] == "/"
    assert client.get("/board").status_code == 200


def test_change_password_needs_current(asha):
    """Voluntary password changes check the current password and the confirmation."""
    data = {"new_password": "another-pass", "confirm_password": "another-pass"}
    r = asha.post("/me/password", data=data | {"current_password": "wrong"})
    assert r.status_code == 400
    r = asha.post(
        "/me/password", data=data | {"current_password": PASSWORD, "confirm_password": "x"}
    )
    assert r.status_code == 400 and "match" in r.text
    r = asha.post("/me/password", data=data | {"current_password": PASSWORD})
    assert r.status_code == 200 and "Password changed" in r.text


def test_short_passwords_rejected(conn, users):
    """Passwords under the minimum length are refused."""
    with pytest.raises(store.UserError):
        store.set_password(conn, users["ravi"], "short")


def test_healthz(app):
    """The health check responds without signing in."""
    with TestClient(app) as client:
        assert client.get("/healthz").text == "ok"
