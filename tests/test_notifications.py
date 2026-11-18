"""Tests for notifications: who is told, the inbox actions, and the JSON mirror."""

from conftest import move, new_task

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

    ravi.patch(f"/api/tasks/{task_id}", json={"title": "Renamed"})
    move(ravi, task_id, "doing")
    ravi.post(f"/api/tasks/{task_id}/updates", json={"body": "Started on it"})

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
    asha.patch(f"/api/tasks/{_first_task(conn)}", json={"title": "Same"})
    assert _rows(conn) == []


def test_set_assignees_tells_added_removed_and_kept(asha, conn, users):
    """New people are told they were assigned, removed people that they were removed, others who joined."""
    new_task(asha, assignee_ids=[users["ravi"], users["meera"]])
    conn.execute("DELETE FROM notifications")
    conn.commit()
    asha.patch(
        f"/api/tasks/{_first_task(conn)}",
        json={"assignee_ids": [users["asha"], users["ravi"]]},
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
    asha.delete(f"/api/tasks/{_first_task(conn)}")
    row = conn.execute("SELECT task_id, task_title, body FROM notifications").fetchone()
    assert tuple(row) == (None, "Doomed", "deleted this task")
    (item,) = ravi.get("/api/notifications").json()
    assert item["task_id"] is None and item["title"] == "Doomed"
    assert item["text"] == "Asha Iyer deleted this task"


def test_notifications_are_private(asha, ravi, conn, users):
    """One person cannot read, change or delete another person's notifications."""
    new_task(asha, assignee_ids=[users["ravi"]])
    (nid,) = [r[0] for r in conn.execute("SELECT id FROM notifications")]
    assert asha.get("/api/notifications").json() == []
    asha.post(f"/api/notifications/{nid}/read")
    asha.delete(f"/api/notifications/{nid}")
    row = conn.execute("SELECT read_at FROM notifications WHERE id = ?", (nid,)).fetchone()
    assert row is not None and row[0] is None


def test_read_unread_dismiss_and_bulk_actions(asha, ravi, conn, users):
    """Mark read and unread, dismiss one, mark all read, and clear the read ones."""
    for title in ("One", "Two", "Three"):
        new_task(asha, title=title, assignee_ids=[users["ravi"]])
    ids = [r[0] for r in conn.execute("SELECT id FROM notifications ORDER BY id")]

    r = ravi.post(f"/api/notifications/{ids[0]}/read")
    assert r.status_code == 204
    assert ravi.get("/api/notifications/unread").json() == {"unread": 2, "newest": ids[-1]}
    ravi.post(f"/api/notifications/{ids[0]}/unread")
    assert ravi.get("/api/notifications/unread").json()["unread"] == 3

    ravi.delete(f"/api/notifications/{ids[1]}")
    assert ravi.get("/api/notifications/unread").json()["unread"] == 2
    ravi.post("/api/notifications/read-all")
    assert ravi.get("/api/notifications/unread").json()["unread"] == 0
    ravi.delete("/api/notifications")
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


def test_list_shows_who_did_what_with_a_ready_made_label(asha, ravi, users):
    """Each notification carries the actor, the task title, a due chip and a time label."""
    new_task(asha, title="GSTR-3B", due="2026-11-12", assignee_ids=[users["ravi"]])
    (item,) = ravi.get("/api/notifications").json()
    assert item["actor"] == "Asha Iyer" and item["title"] == "GSTR-3B"
    assert item["due_label"] == "2 days late" and item["due_tone"] == "red"
    assert item["when"]
    assert ravi.get("/api/notifications/unread").json()["unread"] == 1
    assert asha.get("/api/notifications").json() == []


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
    assert db.migrate(conn) == 5
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


def _kinds(conn):
    """Every notification as ``(recipient username, kind, announce)``, oldest first."""
    return [
        (r["username"], r["kind"], r["announce"])
        for r in conn.execute(
            "SELECT u.username, n.kind, n.announce FROM notifications n "
            "JOIN users u ON u.id = n.user_id ORDER BY n.id"
        )
    ]


def test_each_change_has_its_own_kind(asha, conn, users):
    """Creating, editing, moving, commenting, removing and deleting each use their own kind."""
    new_task(asha, assignee_ids=[users["ravi"], users["meera"]])
    task_id = _first_task(conn)
    asha.patch(f"/api/tasks/{task_id}", json={"title": "Renamed"})
    move(asha, task_id, "doing")
    asha.post(f"/api/tasks/{task_id}/updates", json={"body": "Hello"})
    asha.patch(f"/api/tasks/{task_id}", json={"assignee_ids": [users["ravi"]]})
    asha.delete(f"/api/tasks/{task_id}")
    kinds = [k for _, k, _ in _kinds(conn)]
    assert kinds == [
        "assigned", "assigned",
        "changed", "changed",
        "moved", "moved",
        "comment", "comment",
        "removed", "changed",
        "deleted",
    ]  # fmt: skip


def test_default_settings_alert_for_everything(conn, users):
    """Without any saved choice, every kind is "alert", which is how it behaved before settings."""
    assert store.notification_settings(conn, users["ravi"]) == dict.fromkeys(
        store.NOTIFICATION_KINDS, "alert"
    )


def test_off_skips_only_that_person_and_kind(asha, ravi, conn, users):
    """Turning a kind off stops it for that person alone; their other kinds still arrive."""
    ravi.patch("/api/me/notification-settings", json={"comment": "off"})
    new_task(asha, assignee_ids=[users["ravi"], users["meera"]])
    task_id = _first_task(conn)
    asha.post(f"/api/tasks/{task_id}/updates", json={"body": "Hello"})
    got = {(u, k) for u, k, _ in _kinds(conn)}
    assert ("meera", "comment") in got and ("ravi", "comment") not in got
    assert ("ravi", "assigned") in got


def test_inbox_only_is_listed_but_not_announced(asha, ravi, conn, users):
    """The inbox-only mode keeps a notification in the bell but out of pop-ups and desktop alerts."""
    ravi.patch("/api/me/notification-settings", json={"assigned": "inbox"})
    new_task(asha, assignee_ids=[users["ravi"]])
    assert _kinds(conn) == [("ravi", "assigned", 0)]
    assert ravi.get("/api/notifications").json()[0]["announce"] is False
    assert ravi.get("/api/notifications?unread=true").json() != []
    assert ravi.get("/api/notifications?unread=true&announce=true").json() == []
    # The bell still counts it as unread.
    assert ravi.get("/api/notifications/unread").json()["unread"] == 1


def test_saving_settings_and_going_back_to_default(ravi, conn, users):
    """A saved choice is returned; choosing the default again removes the stored row."""
    r = ravi.patch("/api/me/notification-settings", json={"moved": "inbox", "comment": "off"})
    assert r.status_code == 200
    assert r.json()["moved"] == "inbox" and r.json()["comment"] == "off"
    assert r.json()["assigned"] == "alert"
    r = ravi.patch("/api/me/notification-settings", json={"moved": "alert"})
    assert r.json()["moved"] == "alert"
    assert conn.execute("SELECT COUNT(*) FROM notification_settings").fetchone()[0] == 1
    assert ravi.get("/api/me/notification-settings").json()["comment"] == "off"


def test_invalid_setting_is_refused(ravi, conn, users):
    """An unknown mode or kind is rejected and nothing is saved."""
    assert ravi.patch("/api/me/notification-settings", json={"comment": "shout"}).status_code == 400
    assert ravi.patch("/api/me/notification-settings", json={"nope": "off"}).status_code == 400
    assert conn.execute("SELECT COUNT(*) FROM notification_settings").fetchone()[0] == 0


def test_settings_are_per_person(asha, ravi, conn, users):
    """One person's choices never change another's."""
    ravi.patch("/api/me/notification-settings", json={"assigned": "off"})
    assert store.notification_settings(conn, users["asha"])["assigned"] == "alert"
    assert store.notification_settings(conn, users["meera"])["assigned"] == "alert"


def test_api_notification_settings(app, users):
    """The JSON API reads and changes my settings, and refuses bad values."""
    from conftest import sign_in

    client = sign_in(app, "ravi")
    assert client.get("/api/me/notification-settings").json()["comment"] == "alert"
    r = client.patch("/api/me/notification-settings", json={"comment": "inbox", "moved": "off"})
    assert r.status_code == 200
    assert r.json()["comment"] == "inbox" and r.json()["moved"] == "off"
    bad = client.patch("/api/me/notification-settings", json={"comment": "shout"})
    assert bad.status_code == 400


def test_migration_backfills_the_kind_of_old_notifications(tmp_path):
    """Notifications written before settings existed get a kind worked out from their text."""
    conn = db.connect(tmp_path / "v2.db")
    conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.executescript(db.MIGRATIONS[0])
    conn.execute("PRAGMA user_version = 2")
    conn.execute("PRAGMA foreign_keys = OFF")
    bodies = [
        "assigned you a new task",
        "removed you from this task",
        "commented: hi",
        "deleted this task",
        "marked this Done",
        "moved this to Doing",
        "changed the due date from A to B",
    ]
    for body in bodies:
        conn.execute(
            "INSERT INTO notifications (user_id, task_id, task_title, body, created_at) "
            "VALUES (1, 1, 'T', ?, '2026-11-14T00:00:00+00:00')",
            (body,),
        )
    assert db.migrate(conn) == 5
    kinds = [r[0] for r in conn.execute("SELECT kind FROM notifications ORDER BY id")]
    assert kinds == ["assigned", "removed", "comment", "deleted", "moved", "moved", "changed"]


def test_deadline_and_assignment_changes_are_sticky(asha, ravi, users):
    """Assignments and due-date changes are marked to stay on screen; edits, moves and comments fade."""
    task_id = new_task(asha, assignee_ids=[users["ravi"]])
    asha.patch(f"/api/tasks/{task_id}", json={"due": "2026-11-20"})
    asha.patch(f"/api/tasks/{task_id}", json={"title": "Renamed"})
    asha.post(f"/api/tasks/{task_id}/updates", json={"body": "Hello"})
    move(asha, task_id, "doing")
    sticky = {n["body"]: n["sticky"] for n in ravi.get("/api/notifications").json()}
    assert sticky == {
        "assigned you a new task": True,
        "changed the due date from Sat 14 Nov to Fri 20 Nov": True,
        "renamed this from “A task”": False,
        "commented: Hello": False,
        "moved this to Doing": False,
    }


def test_removal_and_deletion_are_sticky(asha, ravi, users):
    """Being taken off a task or having it deleted also stays on screen until dismissed."""
    task_id = new_task(asha, assignee_ids=[users["ravi"], users["meera"]])
    asha.patch(f"/api/tasks/{task_id}", json={"assignee_ids": [users["meera"]]})
    asha.delete(f"/api/tasks/{task_id}")
    sticky = {n["body"]: n["sticky"] for n in ravi.get("/api/notifications").json()}
    assert sticky["removed you from this task"] is True
    assert sticky["assigned you a new task"] is True
