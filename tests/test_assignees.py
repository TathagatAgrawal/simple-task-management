"""Tests for multiple assignees and the "Showing" filter."""

from conftest import new_task


def _titles(html: str) -> set[str]:
    """Card titles present in a board fragment."""
    import re

    return set(re.findall(r'card-title">([^<]*)<', html))


def test_my_tasks_includes_shared_tasks(asha, ravi, users):
    """A task assigned to two people shows on both their boards."""
    new_task(asha, title="Shared", assignee_ids=[users["asha"], users["ravi"]])
    new_task(asha, title="Mine", assignee_ids=[users["asha"]])
    new_task(asha, title="Nobody")
    assert _titles(asha.get("/board").text) == {"Shared", "Mine"}
    assert _titles(ravi.get("/board").text) == {"Shared"}
    assert _titles(ravi.get("/board?who=all").text) == {"Shared", "Mine", "Nobody"}
    assert _titles(ravi.get("/board?who=none").text) == {"Nobody"}
    assert _titles(ravi.get(f"/board?who={users['asha']}").text) == {"Shared", "Mine"}


def test_set_assignees_logs_changes(asha, conn, users):
    """Replacing the assignee set logs additions and removals."""
    new_task(asha, assignee_ids=[users["asha"]])
    task_id = conn.execute("SELECT id FROM tasks").fetchone()[0]
    r = asha.post(
        f"/tasks/{task_id}/assignees", data={"assignee_ids": [users["ravi"], users["meera"]]}
    )
    assert r.status_code == 204
    body = conn.execute("SELECT body FROM updates ORDER BY id DESC").fetchone()[0]
    assert body == "added Ravi Kumar · added Meera Shah · removed Asha Iyer"

    # Unchecking everyone leaves the task unassigned.
    asha.post(f"/tasks/{task_id}/assignees", data={})
    assert conn.execute("SELECT COUNT(*) FROM task_assignees").fetchone()[0] == 0
    assert "Unassigned" in asha.get("/board?who=all").text


def test_duplicate_assignee_ids_are_ignored(asha, conn, users):
    """Sending the same person twice doesn't break the primary key."""
    new_task(asha, assignee_ids=[users["ravi"], users["ravi"]])
    assert conn.execute("SELECT COUNT(*) FROM task_assignees").fetchone()[0] == 1
