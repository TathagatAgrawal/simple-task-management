"""Tests for the admin-only people management."""

from conftest import move, new_task, sign_in


def test_non_admin_cannot_manage_people(ravi, users):
    """Members get 403 on every admin-only people endpoint."""
    assert ravi.post("/api/people", json={"name": "X", "username": "x1"}).status_code == 403
    assert ravi.delete(f"/api/people/{users['meera']}").status_code == 403
    assert ravi.post(f"/api/people/{users['meera']}/reset-password").status_code == 403
    assert ravi.patch(f"/api/people/{users['meera']}", json={"is_admin": True}).status_code == 403
    assert ravi.get("/api/people").status_code == 200  # everyone may list people


def test_add_person_and_first_sign_in(app, asha):
    """An added person gets a temporary password that works once and must be changed."""
    r = asha.post("/api/people", json={"name": "Neha Rao", "username": "Neha"})
    assert r.status_code == 201
    assert r.json()["person"]["username"] == "neha"
    neha = sign_in(app, "neha", r.json()["temporary_password"])
    assert neha.get("/api/me").json()["must_change_password"] is True


def test_duplicate_and_invalid_usernames(asha):
    """Usernames must be unique and simple."""
    r = asha.post("/api/people", json={"name": "Other Asha", "username": "asha"})
    assert r.status_code == 400
    r = asha.post("/api/people", json={"name": "Bad", "username": "has space"})
    assert r.status_code == 400


def test_remove_person(app, asha, conn, users):
    """Removing someone signs them out and takes them off open tasks only."""
    ravi = sign_in(app, "ravi")
    new_task(asha, title="Open", assignee_ids=[users["ravi"], users["asha"]])
    closed = new_task(asha, title="Closed", assignee_ids=[users["ravi"]])
    move(asha, closed, "done")

    assert asha.delete(f"/api/people/{users['ravi']}").status_code == 204
    assert ravi.get("/api/board").status_code == 401
    rows = conn.execute(
        "SELECT t.title, a.user_id FROM task_assignees a JOIN tasks t ON t.id = a.task_id ORDER BY 1, 2"
    ).fetchall()
    assert [tuple(r) for r in rows] == [("Closed", users["ravi"]), ("Open", users["asha"])]
    updates = asha.get("/api/tasks/1").json()["updates"]
    assert "removed Ravi Kumar (no longer on the team)" in [u["body"] for u in updates]


def test_admin_safety_rails(asha, users):
    """Admins can't remove themselves, and the last admin can't be demoted."""
    assert asha.delete(f"/api/people/{users['asha']}").status_code == 400
    assert asha.patch(f"/api/people/{users['asha']}", json={"is_admin": False}).status_code == 400
    assert asha.patch(f"/api/people/{users['ravi']}", json={"is_admin": True}).status_code == 200
    assert asha.patch(f"/api/people/{users['asha']}", json={"is_admin": False}).status_code == 200


def test_reset_password_signs_person_out(app, asha, users):
    """A reset invalidates existing sessions and returns the new temporary password."""
    meera = sign_in(app, "meera")
    r = asha.post(f"/api/people/{users['meera']}/reset-password")
    assert r.status_code == 200 and r.json()["temporary_password"]
    assert meera.get("/api/board").status_code == 401


def test_removed_person_can_be_added_back(app, asha, conn, users):
    """Re-adding a removed username restores that person instead of failing."""
    asha.delete(f"/api/people/{users['ravi']}")
    r = asha.post("/api/people", json={"name": "Ravi K", "username": "ravi"})
    assert r.status_code == 201
    row = conn.execute(
        "SELECT id, name, is_active, must_change_password FROM users WHERE username = 'ravi'"
    ).fetchone()
    assert tuple(row) == (users["ravi"], "Ravi K", 1, 1)
    again = sign_in(app, "ravi", r.json()["temporary_password"])
    assert again.get("/api/me").json()["must_change_password"] is True
