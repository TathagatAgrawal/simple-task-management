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
    data = asha.get("/api/summary").json()
    assert [t["title"] for t in data["today"]] == ["Due today"]
    assert data["today"][0]["due_label"] == "Today"
    assert data["overdue"] == []


def test_long_groups_keep_every_task_and_label_them(asha, users):
    """The API returns every task in a group; the client decides how many to show."""
    for i in range(5):
        new_task(asha, title=f"Late {i}", due="2026-11-10", assignee_ids=[users["asha"]])
    late = asha.get("/api/summary").json()["overdue"]
    assert len(late) == 5
    assert {t["due_label"] for t in late} == {"4 days late"}
    assert {t["due_tone"] for t in late} == {"red"}


def test_firm_overdue_ignores_the_filter(asha, ravi, users):
    """The overdue count for the whole firm is sent even when "My tasks" hides those tasks."""
    new_task(asha, title="Mine", due="2026-11-10", assignee_ids=[users["asha"]])
    new_task(asha, title="Meera's", due="2026-11-09", assignee_ids=[users["meera"]])
    new_task(asha, title="Later", due="2026-12-20", assignee_ids=[users["meera"]])
    mine = ravi.get("/api/summary", params={"who": "me"}).json()
    assert mine["overdue"] == [] and mine["firm_overdue"] == 2
    assert asha.get("/api/summary", params={"who": "me"}).json()["firm_overdue"] == 2
    assert len(asha.get("/api/summary", params={"who": "all"}).json()["overdue"]) == 2


def test_hidden_overdue_tasks_are_named_with_their_people(asha, ravi, users):
    """The My tasks view names the firm's other overdue work (first names, a few), not just a count."""
    new_task(asha, title="Mine", due="2026-11-10", assignee_ids=[users["ravi"]])
    new_task(asha, title="Meera's", due="2026-11-06", assignee_ids=[users["meera"], users["asha"]])
    new_task(asha, title="Nobody's", due="2026-11-08")
    for i in range(3):
        new_task(asha, title=f"Extra {i}", due="2026-11-07", assignee_ids=[users["meera"]])
    mine = ravi.get("/api/summary", params={"who": "me"}).json()
    names = [(t["title"], t["people"]) for t in mine["others_overdue"]]
    assert len(names) == 3 and mine["firm_overdue"] == 6
    assert ("Mine", "Ravi") not in names  # shown in the overdue list already
    everyone = ravi.get("/api/summary", params={"who": "all"}).json()
    assert everyone["others_overdue"] == []
    asha_view = asha.get("/api/summary", params={"who": "none"}).json()
    assert ("Meera's", "Asha, Meera") in {
        (t["title"], t["people"]) for t in asha_view["others_overdue"]
    }
