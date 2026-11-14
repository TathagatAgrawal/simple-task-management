"""Tests for the "coming up" summary strip."""

from conftest import new_task

from simple_task_management import store


def test_summary_buckets(conn, users):
    """Open tasks fall into overdue / today / soon; done and far-off ones are left out."""
    from conftest import TODAY

    actor = store.get_user(conn, users["asha"])
    for title, due in [
        ("late", "2026-11-10"),
        ("now", "2026-11-14"),
        ("soon", "2026-11-17"),
        ("later", "2026-11-18"),
    ]:
        store.create_task(conn, actor, title=title, due=due, assignee_ids=[users["asha"]])
    done = store.create_task(
        conn, actor, title="finished", due="2026-11-13", assignee_ids=[users["asha"]]
    )
    store.move_task(conn, actor, done, "done", TODAY)

    buckets = store.summary(conn, who="me", me=users["asha"], today=TODAY)
    assert {k: [t["title"] for t in v] for k, v in buckets.items()} == {
        "overdue": ["late"],
        "today": ["now"],
        "soon": ["soon"],
    }
    assert store.summary(conn, who="me", me=users["ravi"], today=TODAY) == {
        "overdue": [],
        "today": [],
        "soon": [],
    }


def test_summary_endpoint_uses_ist_today(asha, users):
    """The endpoint's "today" is the fixed IST date from the test clock."""
    new_task(asha, title="Due today", due="2026-11-14", assignee_ids=[users["asha"]])
    html = asha.get("/summary").text
    assert "Due today" in html
    assert "Nothing overdue" in html


def test_long_groups_collapse_after_three(asha, users):
    """Groups with more than three tasks show the rest behind "Show N more"."""
    for i in range(5):
        new_task(asha, title=f"Late {i}", due="2026-11-10", assignee_ids=[users["asha"]])
    html = asha.get("/summary").text
    assert html.count('class="sum-item"') == 3
    assert html.count('class="sum-item extra"') == 2
    assert "Show 2 more" in html
    assert "4 days late" in html
