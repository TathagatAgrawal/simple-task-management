"""Tests for creating, editing, moving and commenting on tasks, including recurrence."""

from conftest import TODAY, board, board_titles, move, new_task

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
    assert "GSTR-3B - Patel" in board_titles(asha)
    assert _events(conn, task_id) == ["created this · assigned Asha Iyer · repeats monthly"]
    assert tuple(conn.execute("SELECT series_id, repeat_day FROM tasks").fetchone()) == (
        task_id,
        14,
    )


def test_empty_my_tasks_board(ravi):
    """A new person with nothing assigned sees empty columns on "My tasks"."""
    assert board(ravi, who="me") == {"todo": [], "doing": [], "done": []}


def test_create_task_validation(asha):
    """Bad input comes back as a 400 with a readable message."""
    r = asha.post("/api/tasks", json={"title": "   ", "due": TODAY.isoformat()})
    assert r.status_code == 400 and "title" in r.json()["error"]
    r = asha.post("/api/tasks", json={"title": "x", "due": "not-a-date"})
    assert r.status_code == 400 and "due date" in r.json()["error"]
    r = asha.post("/api/tasks", json={"title": "x", "due": TODAY.isoformat(), "repeat": "hourly"})
    assert r.status_code == 400
    r = asha.post(
        "/api/tasks", json={"title": "x", "due": TODAY.isoformat(), "assignee_ids": [999]}
    )
    assert r.status_code == 400


def test_edit_logs_each_change(asha, conn):
    """Only real changes are saved and each one is logged once."""
    task_id = new_task(asha, title="Old")
    r = asha.patch(f"/api/tasks/{task_id}", json={"title": "New", "notes": "", "due": "2026-11-20"})
    assert r.status_code == 200
    assert _events(conn, task_id)[1:] == [
        "renamed this from “Old”",
        "changed the due date from Sat 14 Nov to Fri 20 Nov",
    ]
    asha.patch(f"/api/tasks/{task_id}", json={"title": "New", "due": "2026-11-20"})
    assert len(_events(conn, task_id)) == 3


def test_move_and_reopen(asha, conn):
    """Status moves are logged with natural wording and set done_at."""
    task_id = new_task(asha)
    move(asha, task_id, "doing")
    move(asha, task_id, "done")
    assert conn.execute("SELECT done_at FROM tasks").fetchone()[0]
    move(asha, task_id, "todo")
    assert _events(conn, task_id)[1:] == [
        "moved this to Doing",
        "marked this Done",
        "reopened this (moved to To do)",
    ]
    assert conn.execute("SELECT done_at FROM tasks").fetchone()[0] is None
    assert move(asha, task_id, "nope").status_code == 400


def test_recurring_task_spawns_next_once(asha, conn, users):
    """Marking a repeating task done creates exactly one next occurrence."""
    first = new_task(
        asha, due="2027-01-31", repeat="monthly", assignee_ids=[users["asha"], users["ravi"]]
    )
    move(asha, first, "done")
    move(asha, first, "doing")
    move(asha, first, "done")
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
    move(asha, second, "done")
    third = _ids(conn)[-1]
    assert (
        conn.execute("SELECT due_date FROM tasks WHERE id = ?", (third,)).fetchone()[0]
        == "2027-03-31"
    )


def test_next_occurrence_counts_from_due_not_completion(asha, conn):
    """Finishing late doesn't shift the schedule."""
    first = new_task(asha, due="2026-10-20", repeat="monthly")
    move(asha, first, "done")
    assert conn.execute("SELECT due_date FROM tasks ORDER BY id DESC").fetchone()[0] == "2026-11-20"


def test_stop_repeating(asha, conn):
    """Setting repeat to Never means no next occurrence."""
    task_id = new_task(asha, repeat="weekly")
    asha.patch(f"/api/tasks/{task_id}", json={"repeat": "none"})
    move(asha, task_id, "done")
    assert _ids(conn) == [task_id]
    assert "stopped this repeating" in _events(conn, task_id)


def test_comments_are_returned_raw_for_the_client_to_escape(asha, ravi, conn):
    """Anyone can comment; the API sends the text untouched and the client escapes it."""
    task_id = new_task(asha, notes="Form 24Q")
    r = ravi.post(f"/api/tasks/{task_id}/updates", json={"body": "Called them, see #1 <b>"})
    assert r.status_code == 201
    assert ravi.post(f"/api/tasks/{task_id}/updates", json={"body": "   "}).status_code == 400
    task = asha.get(f"/api/tasks/{task_id}").json()
    assert task["notes"] == "Form 24Q"
    comment = next(u for u in task["updates"] if u["kind"] == "comment")
    assert comment["author"]["name"] == "Ravi Kumar"
    assert comment["body"] == "Called them, see #1 <b>"
    (card,) = board(asha)["todo"]
    assert card["comments"] == 1


def test_delete_then_the_task_is_gone(asha, conn):
    """A deleted task can't be read or moved any more."""
    task_id = new_task(asha)
    assert asha.delete(f"/api/tasks/{task_id}").status_code == 204
    assert asha.get(f"/api/tasks/{task_id}").status_code == 404
    assert move(asha, task_id, "done").status_code == 404


def test_done_column_window(asha, conn):
    """Done shows the last 14 days unless older ones are requested."""
    task_id = new_task(asha, title="Ancient")
    move(asha, task_id, "done")
    conn.execute("UPDATE tasks SET done_at = '2026-10-01T00:00:00+00:00'")
    conn.commit()
    assert "Ancient" not in board_titles(asha)
    assert "Ancient" in board_titles(asha, done_days=3650)


def test_store_update_requires_existing_task(conn, users):
    """Editing a missing task raises a friendly error."""
    actor = store.get_user(conn, users["asha"])
    try:
        store.update_task(conn, actor, 999, title="x", today=TODAY)
    except store.UserError as exc:
        assert "no longer exists" in str(exc)
    else:
        raise AssertionError("expected UserError")
