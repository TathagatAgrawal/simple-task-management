"""Tests for notifications: who is told, the inbox actions, and the JSON mirror."""

from conftest import new_task

from simple_task_management import db, store


def _rows(conn):
    """Every notification as ``(recipient username, body)``, oldest first."""
    return [
        (r["username"], r["body"])
        for r in conn.execute(
            "SELECT u.username, n.body FROM notifications n JOIN users u ON u.id = n.user_id "
            "ORDER BY n.id"
        )
    ]


def _first_task(conn):
    """The id of the only task."""
    return conn.execute("SELECT id FROM tasks").fetchone()[0]


def test_new_task_notifies_assignees_but_not_the_creator(asha, conn, users):
    """Everyone assigned at creation is told, except the person who created it."""
    new_task(asha, assignee_ids=[users["asha"], users["ravi"], users["meera"]])
    assert _rows(conn) == [
        ("ravi", "assigned you a new task"),
        ("meera", "assigned you a new task"),
    ]


def test_self_assigned_task_notifies_nobody(asha, conn, users):
    """Assigning a task only to yourself, or to nobody, creates no notification."""
    new_task(asha, assignee_ids=[users["asha"]])
    new_task(asha, title="Nobody")
    assert _rows(conn) == []


def test_every_change_notifies_the_other_assignees(asha, ravi, conn, users):
    """Edits, moves and comments by one assignee reach the others, never the actor."""
    new_task(asha, assignee_ids=[users["asha"], users["ravi"], users["meera"]])
    conn.execute("DELETE FROM notifications")
    conn.commit()
    task_id = _first_task(conn)

    ravi.post(f"/tasks/{task_id}", data={"title": "Renamed"})
    ravi.post(f"/tasks/{task_id}/move", data={"status": "doing"})
    ravi.post(f"/tasks/{task_id}/updates", data={"body": "Started on it"})

    assert _rows(conn) == [
        ("asha", "renamed this from “A task”"),
        ("meera", "renamed this from “A task”"),
        ("asha", "moved this to Doing"),
        ("meera", "moved this to Doing"),
        ("asha", "commented: Started on it"),
        ("meera", "commented: Started on it"),
    ]


def test_unchanged_save_notifies_nobody(asha, conn, users):
    """Saving a field without changing it is not a change."""
    new_task(asha, title="Same", assignee_ids=[users["ravi"]])
    conn.execute("DELETE FROM notifications")
    conn.commit()
    asha.post(f"/tasks/{_first_task(conn)}", data={"title": "Same"})
    assert _rows(conn) == []


def test_set_assignees_tells_added_removed_and_kept(asha, conn, users):
    """New people are told they were assigned, removed people that they were removed, others who joined."""
    new_task(asha, assignee_ids=[users["ravi"], users["meera"]])
    conn.execute("DELETE FROM notifications")
    conn.commit()
    asha.post(
        f"/tasks/{_first_task(conn)}/assignees",
        data={"assignee_ids": [users["asha"], users["ravi"]]},
    )
    assert sorted(_rows(conn)) == [
        ("meera", "removed you from this task"),
        ("ravi", "added Asha Iyer · removed Meera Shah"),
    ]


def test_delete_notifies_assignees_and_keeps_the_title(asha, ravi, conn, users):
    """Deleting a task tells its assignees, and their notification still names the task."""
    new_task(asha, title="Doomed", assignee_ids=[users["ravi"]])
    conn.execute("DELETE FROM notifications")
    conn.commit()
    asha.post(f"/tasks/{_first_task(conn)}/delete")
    row = conn.execute("SELECT task_id, task_title, body FROM notifications").fetchone()
    assert tuple(row) == (None, "Doomed", "deleted this task")
    html = ravi.get("/notifications").text
    assert "Doomed" in html and "deleted this task" in html


def test_notifications_are_private(asha, ravi, conn, users):
    """One person cannot read, change or delete another person's notifications."""
    new_task(asha, assignee_ids=[users["ravi"]])
    (nid,) = [r[0] for r in conn.execute("SELECT id FROM notifications")]
    assert "assigned you a new task" not in asha.get("/notifications").text
    asha.post(f"/notifications/{nid}/read")
    asha.post(f"/notifications/{nid}/dismiss")
    row = conn.execute("SELECT read_at FROM notifications WHERE id = ?", (nid,)).fetchone()
    assert row is not None and row[0] is None


def test_read_unread_dismiss_and_bulk_actions(asha, ravi, conn, users):
    """Mark read and unread, dismiss one, mark all read, and clear the read ones."""
    for title in ("One", "Two", "Three"):
        new_task(asha, title=title, assignee_ids=[users["ravi"]])
    ids = [r[0] for r in conn.execute("SELECT id FROM notifications ORDER BY id")]

    r = ravi.post(f"/notifications/{ids[0]}/read")
    assert r.status_code == 204 and r.headers["HX-Trigger"] == "notifications-changed"
    assert store.notification_counts(conn, users["ravi"]) == (2, ids[-1])
    ravi.post(f"/notifications/{ids[0]}/unread")
    assert store.notification_counts(conn, users["ravi"])[0] == 3

    ravi.post(f"/notifications/{ids[1]}/dismiss")
    assert store.notification_counts(conn, users["ravi"])[0] == 2
    ravi.post("/notifications/read-all")
    assert store.notification_counts(conn, users["ravi"])[0] == 0
    ravi.post("/notifications/clear-read")
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


def test_badge_and_list_fragments(asha, ravi, users):
    """The bell shows the unread count and newest id; the list shows who did what."""
    new_task(asha, title="GSTR-3B", assignee_ids=[users["ravi"]])
    badge = ravi.get("/notifications/badge").text
    assert 'data-unread="1"' in badge and 'aria-label="Notifications, 1 unread"' in badge
    listing = ravi.get("/notifications").text
    assert "Asha Iyer" in listing and "GSTR-3B" in listing and "Unread." in listing
    assert "all caught up" in asha.get("/notifications").text


def test_old_read_notifications_are_pruned(asha, conn, users):
    """Read notifications older than a month are deleted when a new one is written."""
    new_task(asha, assignee_ids=[users["ravi"]])
    conn.execute("UPDATE notifications SET read_at = '2020-01-01T00:00:00+00:00'")
    conn.commit()
    new_task(asha, title="Fresh", assignee_ids=[users["ravi"]])
    assert len(_rows(conn)) == 1


def test_ids_are_never_reused(asha, conn, users):
    """Deleting the newest notification must not let the next one reuse its id."""
    new_task(asha, assignee_ids=[users["ravi"]])
    first = conn.execute("SELECT MAX(id) FROM notifications").fetchone()[0]
    conn.execute("DELETE FROM notifications")
    conn.commit()
    new_task(asha, title="Next", assignee_ids=[users["ravi"]])
    assert conn.execute("SELECT MAX(id) FROM notifications").fetchone()[0] > first


def test_migration_adds_the_table_to_a_version_1_database(tmp_path):
    """An existing version 1 database gains the notifications table on startup."""
    conn = db.connect(tmp_path / "old.db")
    conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("PRAGMA user_version = 1")
    assert db.migrate(conn) == 2
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


def test_service_worker_is_served_from_the_root(asha):
    """The service worker lives at /sw.js so its scope covers the whole site."""
    r = asha.get("/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "notificationclick" in r.text
