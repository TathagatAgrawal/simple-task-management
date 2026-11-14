"""Tests for the admin-only people management."""

import re

from conftest import new_task, sign_in


def test_non_admin_cannot_manage_people(ravi, users):
    """Members get 403 on every people endpoint."""
    assert ravi.get("/people").status_code == 403
    assert ravi.post("/people", data={"name": "X", "username": "x1"}).status_code == 403
    assert ravi.post(f"/people/{users['meera']}/remove").status_code == 403
    assert ravi.post(f"/people/{users['meera']}/reset").status_code == 403


def test_add_person_and_first_sign_in(app, asha):
    """An added person gets a temporary password that works once and must be changed."""
    r = asha.post("/people", data={"name": "Neha Rao", "username": "Neha"})
    assert r.status_code == 200 and r.headers["HX-Trigger"] == "people-changed"
    temp = re.search(r"<code>([^<]+)</code>", r.text).group(1)
    neha = sign_in(app, "neha", temp)
    assert "choose your own password" in neha.get("/").text


def test_duplicate_and_invalid_usernames(asha):
    """Usernames must be unique and simple."""
    assert asha.post("/people", data={"name": "Other Asha", "username": "asha"}).status_code == 400
    assert asha.post("/people", data={"name": "Bad", "username": "has space"}).status_code == 400


def test_remove_person(app, asha, conn, users):
    """Removing someone signs them out and takes them off open tasks only."""
    ravi = sign_in(app, "ravi")
    new_task(asha, title="Open", assignee_ids=[users["ravi"], users["asha"]])
    new_task(asha, title="Closed", assignee_ids=[users["ravi"]])
    closed = conn.execute("SELECT id FROM tasks WHERE title = 'Closed'").fetchone()[0]
    asha.post(f"/tasks/{closed}/move", data={"status": "done"})

    r = asha.post(f"/people/{users['ravi']}/remove")
    assert r.status_code == 200 and "Removed Ravi Kumar" in r.text
    assert ravi.get("/board").status_code == 401
    rows = conn.execute(
        "SELECT t.title, a.user_id FROM task_assignees a JOIN tasks t ON t.id = a.task_id ORDER BY 1, 2"
    ).fetchall()
    assert [tuple(r) for r in rows] == [("Closed", users["ravi"]), ("Open", users["asha"])]
    assert "removed Ravi Kumar (no longer on the team)" in asha.get("/tasks/1").text


def test_admin_safety_rails(asha, users):
    """Admins can't remove themselves, and the last admin can't be demoted."""
    assert asha.post(f"/people/{users['asha']}/remove").status_code == 400
    assert asha.post(f"/people/{users['asha']}/admin", data={"make_admin": 0}).status_code == 400
    assert asha.post(f"/people/{users['ravi']}/admin", data={"make_admin": 1}).status_code == 200
    assert asha.post(f"/people/{users['asha']}/admin", data={"make_admin": 0}).status_code == 200


def test_reset_password_signs_person_out(app, asha, users):
    """A reset invalidates existing sessions and shows the new temporary password."""
    meera = sign_in(app, "meera")
    r = asha.post(f"/people/{users['meera']}/reset")
    assert "<code>" in r.text
    assert meera.get("/board").status_code == 401


def test_removed_person_can_be_added_back(app, asha, conn, users):
    """Re-adding a removed username restores that person instead of failing."""
    asha.post(f"/people/{users['ravi']}/remove")
    r = asha.post("/people", data={"name": "Ravi K", "username": "ravi"})
    assert r.status_code == 200
    row = conn.execute(
        "SELECT id, name, is_active, must_change_password FROM users WHERE username = 'ravi'"
    ).fetchone()
    assert tuple(row) == (users["ravi"], "Ravi K", 1, 1)
    temp = re.search(r"<code>([^<]+)</code>", r.text).group(1)
    assert "choose your own password" in sign_in(app, "ravi", temp).get("/").text
