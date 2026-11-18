"""Tests for multiple assignees and the "Showing" filter."""

from conftest import board_titles, new_task


def test_my_tasks_includes_shared_tasks(asha, ravi, users):
    """A task assigned to two people shows on both their boards."""
    new_task(asha, title="Shared", assignee_ids=[users["asha"], users["ravi"]])
    new_task(asha, title="Mine", assignee_ids=[users["asha"]])
    new_task(asha, title="Nobody")
    assert board_titles(asha, "me") == {"Shared", "Mine"}
    assert board_titles(ravi, "me") == {"Shared"}
    assert board_titles(ravi, "all") == {"Shared", "Mine", "Nobody"}
    assert board_titles(ravi, "none") == {"Nobody"}
    assert board_titles(ravi, str(users["asha"])) == {"Shared", "Mine"}


def test_set_assignees_logs_changes(asha, conn, users):
    """Replacing the assignee set logs additions and removals."""
    task_id = new_task(asha, assignee_ids=[users["asha"]])
    r = asha.patch(f"/api/tasks/{task_id}", json={"assignee_ids": [users["ravi"], users["meera"]]})
    assert r.status_code == 200
    body = conn.execute("SELECT body FROM updates ORDER BY id DESC").fetchone()[0]
    assert body == "added Ravi Kumar · added Meera Shah · removed Asha Iyer"

    # Unchecking everyone leaves the task unassigned.
    r = asha.patch(f"/api/tasks/{task_id}", json={"assignee_ids": []})
    assert r.json()["assignees"] == []
    assert conn.execute("SELECT COUNT(*) FROM task_assignees").fetchone()[0] == 0
