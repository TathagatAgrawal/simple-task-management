"""Tests for the JSON API under /api."""

import pytest
from conftest import PASSWORD, TODAY, sign_in
from fastapi.testclient import TestClient

from simple_task_management import store


def api_client(app, username: str, password: str = PASSWORD) -> TestClient:
    """A client signed in through ``POST /api/session`` that sends the bearer token."""
    client = TestClient(app)
    client.__enter__()
    response = client.post("/api/session", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.cookies.clear()  # prove the bearer token alone is enough
    client.headers["Authorization"] = "Bearer " + response.json()["token"]
    return client


@pytest.fixture
def api(app, users):
    """JSON API client signed in as the admin (asha)."""
    client = api_client(app, "asha")
    yield client
    client.__exit__(None, None, None)


@pytest.fixture
def api_ravi(app, users):
    """JSON API client signed in as a non-admin (ravi)."""
    client = api_client(app, "ravi")
    yield client
    client.__exit__(None, None, None)


def make_task(api, **fields) -> dict:
    """Create a task through the API and return its JSON."""
    body = {"title": "File GSTR-3B", "due": TODAY.isoformat()} | fields
    response = api.post("/api/tasks", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------ sign-in


def test_sign_in_returns_a_token_and_the_user(app, users):
    """Good credentials give a bearer token and who you are."""
    with TestClient(app) as client:
        r = client.post("/api/session", json={"username": "asha", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["username"] == "asha"
    assert body["user"]["is_admin"] is True
    assert "password_hash" not in body["user"]


def test_wrong_password_is_a_json_401(app, users):
    """Bad credentials give a JSON error, not a page or a redirect."""
    with TestClient(app) as client:
        r = client.post("/api/session", json={"username": "asha", "password": "nope"})
    assert r.status_code == 401
    assert r.json() == {"error": "Wrong username or password."}


def test_signed_out_requests_are_a_json_401(app, users):
    """The API never redirects to the login page."""
    with TestClient(app) as client:
        r = client.get("/api/board", follow_redirects=False)
    assert r.status_code == 401
    assert r.json()["error"]


def test_signing_out_ends_the_token(api):
    """After DELETE /api/session the token stops working."""
    assert api.delete("/api/session").status_code == 204
    assert api.get("/api/me").status_code == 401


def test_cookie_sign_in_needs_the_csrf_token_to_write(app, users):
    """A browser session cookie works too, but unsafe requests must carry X-CSRF-Token."""
    with TestClient(app) as client:
        login = client.post("/api/session", json={"username": "asha", "password": PASSWORD})
        csrf = login.json()["user"]["csrf_token"]
        body = {"title": "From a cookie", "due": TODAY.isoformat()}
        assert client.get("/api/board").status_code == 200
        assert client.post("/api/tasks", json=body).status_code == 403
        assert (
            client.post("/api/tasks", json=body, headers={"X-CSRF-Token": csrf}).status_code == 201
        )


def test_the_html_session_also_works_for_the_api(app, users):
    """Someone signed in on the web page can call the API with the same cookie."""
    client = sign_in(app, "asha")
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["username"] == "asha"
    client.__exit__(None, None, None)


def test_a_temporary_password_must_be_replaced_first(app, conn):
    """Until they choose a password, only the password change is allowed."""
    store.create_user(conn, "Neha Rao", "neha", "temp-pass-1")
    client = api_client(app, "neha", "temp-pass-1")
    assert client.get("/api/board").status_code == 403
    assert client.get("/api/me").json()["must_change_password"] is True
    r = client.post(
        "/api/me/password",
        json={"new_password": "brand-new-pass", "confirm_password": "brand-new-pass"},
    )
    assert r.status_code == 204
    assert client.get("/api/board").status_code == 200


def test_theme_can_be_changed(api):
    """PATCH /api/me saves the theme; unknown themes are rejected."""
    assert api.patch("/api/me", json={"theme": "dark"}).json()["theme"] == "dark"
    assert api.get("/api/me").json()["theme"] == "dark"
    assert api.patch("/api/me", json={"theme": "pink"}).status_code == 400


# ------------------------------------------------------------ tasks


def test_create_and_read_a_task(api, users):
    """Creating returns the task; GET returns it again with its first update."""
    task = make_task(api, assignee_ids=[users["ravi"]], repeat="monthly", notes="Check ITC")
    assert task["status"] == "todo"
    assert task["repeat"] == "monthly"
    assert task["notes"] == "Check ITC"
    assert [a["name"] for a in task["assignees"]] == ["Ravi Kumar"]
    got = api.get(f"/api/tasks/{task['id']}").json()
    assert got["updates"][0]["kind"] == "event"
    assert "created this" in got["updates"][0]["body"]
    assert got["updates"][0]["author"]["name"] == "Asha Iyer"


def test_bad_input_is_a_json_error(api):
    """Validation problems are ``{"error": ...}`` with 400 (our rules) or 422 (missing fields)."""
    bad_date = api.post("/api/tasks", json={"title": "x", "due": "tomorrow"})
    assert bad_date.status_code == 400
    assert "error" in bad_date.json()
    missing = api.post("/api/tasks", json={"due": TODAY.isoformat()})
    assert missing.status_code == 422
    assert missing.json()["error"].startswith("title")
    typo = api.post("/api/tasks", json={"title": "x", "due": TODAY.isoformat(), "duee": "1"})
    assert typo.status_code == 422


def test_board_and_summary(api, users):
    """The board groups cards by status and the summary buckets open tasks by due date."""
    mine = make_task(api, title="Mine", assignee_ids=[users["asha"]])
    make_task(api, title="Nobody's", due="2026-11-01")
    board = api.get("/api/board").json()
    assert [c["id"] for c in board["todo"]] == [mine["id"]]
    assert board["todo"][0]["due_label"] == "Today"
    assert board["doing"] == [] and board["done"] == []
    everyone = api.get("/api/board", params={"who": "all"}).json()
    assert len(everyone["todo"]) == 2
    summary = api.get("/api/summary", params={"who": "all"}).json()
    assert [t["title"] for t in summary["overdue"]] == ["Nobody's"]
    assert [t["title"] for t in summary["today"]] == ["Mine"]
    assert summary["soon"] == []


def test_patch_changes_several_fields_and_logs_them(api, users):
    """One PATCH can change fields, status and assignees, each logged in the updates."""
    task = make_task(api)
    r = api.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "GSTR-3B - Patel", "status": "doing", "assignee_ids": [users["meera"]]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "GSTR-3B - Patel"
    assert body["status"] == "doing"
    assert [a["name"] for a in body["assignees"]] == ["Meera Shah"]
    assert body["next_task_id"] is None
    events = [u["body"] for u in body["updates"] if u["kind"] == "event"]
    assert any("moved this to Doing" in e for e in events)


def test_a_bad_value_changes_nothing(api):
    """If one field is invalid, none of the others are applied."""
    task = make_task(api, title="Original")
    r = api.patch(f"/api/tasks/{task['id']}", json={"title": "Changed", "status": "flying"})
    assert r.status_code == 400
    assert api.get(f"/api/tasks/{task['id']}").json()["title"] == "Original"


def test_finishing_a_recurring_task_creates_the_next_one(api):
    """Moving a repeating task to done reports the new occurrence's id."""
    task = make_task(api, repeat="monthly")
    r = api.patch(f"/api/tasks/{task['id']}", json={"status": "done"}).json()
    assert r["status"] == "done"
    assert r["next_task_id"]
    nxt = api.get(f"/api/tasks/{r['next_task_id']}").json()
    assert nxt["status"] == "todo"
    assert nxt["due"] == "2026-12-14"


def test_comments(api):
    """Posting an update shows up in the task's thread, written by the poster."""
    task = make_task(api)
    r = api.post(f"/api/tasks/{task['id']}/updates", json={"body": "Called the client."})
    assert r.status_code == 201
    last = r.json()["updates"][-1]
    assert (last["kind"], last["body"], last["author"]["name"]) == (
        "comment",
        "Called the client.",
        "Asha Iyer",
    )
    assert api.post(f"/api/tasks/{task['id']}/updates", json={"body": "  "}).status_code == 400


def test_delete_then_404(api):
    """A deleted task is gone, and the API says so with a JSON 404."""
    task = make_task(api)
    assert api.delete(f"/api/tasks/{task['id']}").status_code == 204
    gone = api.get(f"/api/tasks/{task['id']}")
    assert gone.status_code == 404
    assert gone.json()["error"]
    assert api.patch(f"/api/tasks/{task['id']}", json={"title": "x"}).status_code == 404
    assert api.delete(f"/api/tasks/{task['id']}").status_code == 404


def test_unknown_api_paths_are_json_404s(api):
    """Even a wrong URL gets a JSON error."""
    r = api.get("/api/nope")
    assert r.status_code == 404
    assert "error" in r.json()


# ------------------------------------------------------------ people


def test_anyone_can_list_people(api_ravi):
    """The people list (for assignee pickers) is open to every signed-in person."""
    names = [p["name"] for p in api_ravi.get("/api/people").json()]
    assert names == ["Asha Iyer", "Meera Shah", "Ravi Kumar"]


def test_only_admins_manage_people(api_ravi, users):
    """Adding, changing, resetting and removing people are admin-only."""
    assert (
        api_ravi.post("/api/people", json={"name": "Neha Rao", "username": "neha"}).status_code
        == 403
    )
    assert (
        api_ravi.patch(f"/api/people/{users['meera']}", json={"is_admin": True}).status_code == 403
    )
    assert api_ravi.post(f"/api/people/{users['meera']}/reset-password").status_code == 403
    assert api_ravi.delete(f"/api/people/{users['meera']}").status_code == 403


def test_admin_adds_changes_resets_and_removes_a_person(app, api, users):
    """The whole people lifecycle through the API."""
    added = api.post("/api/people", json={"name": "Neha Rao", "username": "neha"})
    assert added.status_code == 201
    temp = added.json()["temporary_password"]
    person = added.json()["person"]
    assert person["username"] == "neha" and person["is_admin"] is False
    # the temporary password works and forces a change
    assert api_client(app, "neha", temp).get("/api/me").json()["must_change_password"] is True
    promoted = api.patch(f"/api/people/{person['id']}", json={"is_admin": True})
    assert promoted.json()["is_admin"] is True
    reset = api.post(f"/api/people/{person['id']}/reset-password").json()
    assert reset["temporary_password"] != temp
    assert api.delete(f"/api/people/{person['id']}").status_code == 204
    assert "Neha Rao" not in [p["name"] for p in api.get("/api/people").json()]
    assert api.delete("/api/people/9999").status_code == 404
    dup = api.post("/api/people", json={"name": "Asha Again", "username": "!!"})
    assert dup.status_code == 400


# ------------------------------------------------------------ schema


def test_openapi_schema_describes_the_api(app, users):
    """The schema is published for the API only; the HTML app stays unadvertised."""
    with TestClient(app) as client:
        schema = client.get("/api/openapi.json").json()
        assert "/tasks/{task_id}" in schema["paths"]
        assert client.get("/openapi.json").status_code == 404


def test_api_notifications(app, users):
    """The JSON API lists, reads, dismisses and counts my notifications."""
    from conftest import sign_in

    asha_client = sign_in(app, "asha")
    ravi_client = sign_in(app, "ravi")
    asha_client.post(
        "/api/tasks",
        json={"title": "Filing", "due": "2026-11-20", "assignee_ids": [users["ravi"]]},
    )
    unread = ravi_client.get("/api/notifications/unread").json()
    assert unread["unread"] == 1
    items = ravi_client.get("/api/notifications?unread=true").json()
    assert items[0]["text"] == "Asha Iyer assigned you a new task"
    assert items[0]["detail"] == "Filing" and items[0]["read"] is False
    assert items[0]["actor"] == "Asha Iyer" and items[0]["kind"] == "assigned"
    assert items[0]["due_label"] == "Fri 20 Nov" and items[0]["announce"] is True
    assert ravi_client.get(f"/api/notifications?after={unread['newest']}").json() == []
    nid = items[0]["id"]
    assert ravi_client.post(f"/api/notifications/{nid}/read").status_code == 204
    assert ravi_client.get("/api/notifications/unread").json()["unread"] == 0
    assert ravi_client.delete("/api/notifications").status_code == 204
    assert ravi_client.get("/api/notifications").json() == []
