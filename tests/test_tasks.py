"""Tests for creating, editing, moving and commenting on tasks, including recurrence."""

import json

from conftest import TODAY, new_task

from simple_task_management import store


def _ids(conn):
    """All task ids, oldest first."""
    return [r[0] for r in conn.execute("SELECT id FROM tasks ORDER BY id")]


def _events(conn, task_id):
    """Event bodies on a task's thread, in order."""
    return [
        r[0]
        for r in conn.execute(
            "SELECT body FROM updates WHERE task_id = ? AND kind = 'event' ORDER BY id", (task_id,)
        )
    ]


def test_create_task_appears_on_board(asha, conn, users):
    """A new task shows on the creator's board and logs a created event."""
    new_task(asha, title="GSTR-3B - Patel", assignee_ids=[users["asha"]], repeat="monthly")
    (task_id,) = _ids(conn)
    assert "GSTR-3B - Patel" in asha.get("/board?who=all").text
    assert _events(conn, task_id) == ["created this · assigned Asha Iyer · repeats monthly"]
    assert tuple(conn.execute("SELECT series_id, repeat_day FROM tasks").fetchone()) == (
        task_id,
        14,
    )


def test_create_task_opens_it(asha, conn):
    """Creating a task tells the page to open it, so it's visible whatever the filter."""
    r = asha.post("/tasks", data={"title": "For Ravi", "due": TODAY.isoformat()})
    task_id = conn.execute("SELECT id FROM tasks").fetchone()[0]
    trigger = json.loads(r.headers["HX-Trigger"])
    assert trigger == {"tasks-changed": None, "task-created": {"id": task_id}}


def test_apostrophes_are_not_mistaken_for_task_links(asha, conn):
    """An escaped apostrophe (&#39;) must not turn into a "#39" task link."""
    new_task(asha)
    (task_id,) = _ids(conn)
    asha.post(f"/tasks/{task_id}/updates", data={"body": "I'll file it, see #7"})
    panel = asha.get(f"/tasks/{task_id}").text
    assert "I&#39;ll file it, see" in panel
    assert 'hx-get="/tasks/39"' not in panel
    assert 'hx-get="/tasks/7"' in panel


def test_empty_my_tasks_board_explains_where_tasks_are(ravi):
    """A new person with nothing assigned is pointed at the Everyone filter."""
    html = ravi.get("/board?who=me").text
    assert "Nothing is assigned to you yet" in html
    assert "Drag a card here" not in html
    assert "Nothing is assigned" not in ravi.get("/board?who=all").text


def test_create_task_validation(asha):
    """Bad input comes back as a 400 with a readable message."""
    r = asha.post("/tasks", data={"title": "   ", "due": TODAY.isoformat()})
    assert r.status_code == 400 and "title" in r.text
    r = asha.post("/tasks", data={"title": "x", "due": "not-a-date"})
    assert r.status_code == 400 and "due date" in r.text
    r = asha.post("/tasks", data={"title": "x", "due": TODAY.isoformat(), "repeat": "hourly"})
    assert r.status_code == 400
    r = asha.post("/tasks", data={"title": "x", "due": TODAY.isoformat(), "assignee_ids": [999]})
    assert r.status_code == 400


def test_edit_logs_each_change(asha, conn):
    """Only real changes are saved and each one is logged once."""
    new_task(asha, title="Old")
    (task_id,) = _ids(conn)
    r = asha.post(
        f"/tasks/{task_id}",
        data={"title": "New", "notes": "", "due": "2026-11-20", "repeat": "none"},
    )
    assert r.status_code == 204 and r.headers["HX-Trigger"] == "tasks-changed"
    assert _events(conn, task_id)[1:] == [
        "renamed this from “Old”",
        "changed the due date from Sat 14 Nov to Fri 20 Nov",
    ]
    asha.post(f"/tasks/{task_id}", data={"title": "New", "due": "2026-11-20"})
    assert len(_events(conn, task_id)) == 3


def test_move_and_reopen(asha, conn):
    """Status moves are logged with natural wording and set done_at."""
    new_task(asha)
    (task_id,) = _ids(conn)
    asha.post(f"/tasks/{task_id}/move", data={"status": "doing"})
    asha.post(f"/tasks/{task_id}/move", data={"status": "done"})
    assert conn.execute("SELECT done_at FROM tasks").fetchone()[0]
    asha.post(f"/tasks/{task_id}/move", data={"status": "todo"})
    assert _events(conn, task_id)[1:] == [
        "moved this to Doing",
        "marked this Done",
        "reopened this (moved to To do)",
    ]
    assert conn.execute("SELECT done_at FROM tasks").fetchone()[0] is None
    assert asha.post(f"/tasks/{task_id}/move", data={"status": "nope"}).status_code == 400


def test_recurring_task_spawns_next_once(asha, conn, users):
    """Marking a repeating task done creates exactly one next occurrence."""
    new_task(asha, due="2027-01-31", repeat="monthly", assignee_ids=[users["asha"], users["ravi"]])
    (first,) = _ids(conn)
    asha.post(f"/tasks/{first}/move", data={"status": "done"})
    asha.post(f"/tasks/{first}/move", data={"status": "doing"})
    asha.post(f"/tasks/{first}/move", data={"status": "done"})
    _, second = _ids(conn)
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (second,)).fetchone()
    assert row["due_date"] == "2027-02-28"
    assert row["status"] == "todo" and row["prev_task_id"] == first and row["series_id"] == first
    assert row["repeat_day"] == 31
    people = {
        r[0]
        for r in conn.execute("SELECT user_id FROM task_assignees WHERE task_id = ?", (second,))
    }
    assert people == {users["asha"], users["ravi"]}
    assert f"#{second}" in _events(conn, first)[2]

    # The month after February returns to the 31st.
    asha.post(f"/tasks/{second}/move", data={"status": "done"})
    third = _ids(conn)[-1]
    assert (
        conn.execute("SELECT due_date FROM tasks WHERE id = ?", (third,)).fetchone()[0]
        == "2027-03-31"
    )


def test_next_occurrence_counts_from_due_not_completion(asha, conn):
    """Finishing late doesn't shift the schedule."""
    new_task(asha, due="2026-10-20", repeat="monthly")
    (first,) = _ids(conn)
    asha.post(f"/tasks/{first}/move", data={"status": "done"})
    assert conn.execute("SELECT due_date FROM tasks ORDER BY id DESC").fetchone()[0] == "2026-11-20"


def test_stop_repeating(asha, conn):
    """Setting repeat to Never means no next occurrence."""
    new_task(asha, repeat="weekly")
    (task_id,) = _ids(conn)
    asha.post(f"/tasks/{task_id}", data={"repeat": "none"})
    asha.post(f"/tasks/{task_id}/move", data={"status": "done"})
    assert _ids(conn) == [task_id]
    assert "stopped this repeating" in _events(conn, task_id)


def test_comments_and_panel(asha, ravi, conn):
    """Anyone can comment; the panel shows comments, events and linked task refs."""
    new_task(asha, notes="Form 24Q")
    (task_id,) = _ids(conn)
    assert (
        ravi.post(f"/tasks/{task_id}/updates", data={"body": "Called them, see #1 <b>"}).status_code
        == 204
    )
    assert ravi.post(f"/tasks/{task_id}/updates", data={"body": "   "}).status_code == 400
    panel = asha.get(f"/tasks/{task_id}").text
    assert "Ravi Kumar" in panel and "Form 24Q" in panel
    assert 'hx-get="/tasks/1"' in panel
    assert "&lt;b&gt;" in panel  # comment HTML is escaped
    assert 'title="1 comment"' in asha.get("/board?who=all").text


def test_delete_closes_panel(asha, conn):
    """A deleted task's panel renders empty so the client closes it."""
    new_task(asha)
    (task_id,) = _ids(conn)
    assert asha.post(f"/tasks/{task_id}/delete").status_code == 204
    assert asha.get(f"/tasks/{task_id}").text == ""
    assert asha.post(f"/tasks/{task_id}/move", data={"status": "done"}).status_code == 400


def test_done_column_window(asha, conn):
    """Done shows the last 14 days unless older ones are requested."""
    new_task(asha, title="Ancient")
    (task_id,) = _ids(conn)
    asha.post(f"/tasks/{task_id}/move", data={"status": "done"})
    conn.execute("UPDATE tasks SET done_at = '2026-10-01T00:00:00+00:00'")
    conn.commit()
    assert "Ancient" not in asha.get("/board?who=all").text
    assert "Ancient" in asha.get("/board?who=all&done_days=3650").text


def test_store_update_requires_existing_task(conn, users):
    """Editing a missing task raises a friendly error."""
    actor = store.get_user(conn, users["asha"])
    try:
        store.update_task(conn, actor, 999, title="x", today=TODAY)
    except store.UserError as exc:
        assert "no longer exists" in str(exc)
    else:
        raise AssertionError("expected UserError")
