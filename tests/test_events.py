"""Tests for live updates: the hub, the event stream and what the API announces."""

import asyncio

from conftest import move, new_task
from fastapi.testclient import TestClient

from simple_task_management import events


def _collect(hub: events.Hub, act, wanted: int) -> list[set[str]]:
    """Subscribe, run ``act`` on a worker thread, and return the first ``wanted`` messages."""

    async def scenario() -> list[set[str]]:
        queue = hub.subscribe()
        try:
            await asyncio.to_thread(act)
            topics: set[str] = set()
            for _ in range(wanted):
                topics.add(await asyncio.wait_for(queue.get(), 2))
            return [topics]
        finally:
            hub.unsubscribe(queue)

    return asyncio.run(scenario())


def test_stream_says_ready_then_pushes_merged_topics():
    """A new page is told it is connected, then gets each burst of changes as one message."""

    async def scenario() -> list[str]:
        hub = events.Hub()
        stream = events.stream(hub, heartbeat=0.05)
        seen = [await anext(stream)]
        seen.append(await anext(stream))  # nothing happens, so a ping keeps it alive
        hub.publish("tasks", "notifications", "tasks")
        seen.append(await anext(stream))
        await stream.aclose()
        assert not hub._subscribers  # a closed page is forgotten
        return seen

    ready, ping, data = asyncio.run(scenario())
    assert '["ready"]' in ready and ready.startswith("retry:")
    assert ping == ": ping\n\n"
    assert data == 'data: ["notifications", "tasks"]\n\n'


def test_closing_the_hub_ends_open_streams():
    """At shutdown every open stream finishes instead of holding the server up."""

    async def scenario() -> list[str]:
        hub = events.Hub()
        stream = events.stream(hub, heartbeat=5)
        out = [await anext(stream)]
        hub.close()
        out.extend([chunk async for chunk in stream])
        return out

    assert len(asyncio.run(scenario())) == 1


def test_the_event_stream_requires_a_session(app, users):
    """Signed-out pages cannot listen."""
    with TestClient(app) as client:
        assert client.get("/api/events").status_code == 401


def test_task_changes_announce_tasks_and_notifications(app, asha, users):
    """Creating, editing and commenting tell every page to refresh the board and the bell."""
    [topics] = _collect(app.state.hub, lambda: new_task(asha, assignee_ids=[users["ravi"]]), 2)
    assert topics == {"tasks", "notifications"}

    task_id = new_task(asha)
    [topics] = _collect(app.state.hub, lambda: move(asha, task_id, "doing"), 2)
    assert topics == {"tasks", "notifications"}


def test_inbox_actions_announce_notifications_only(app, ravi):
    """Marking everything read refreshes the bell on other tabs, and nothing else."""
    [topics] = _collect(app.state.hub, lambda: ravi.post("/api/notifications/read-all"), 1)
    assert topics == {"notifications"}


def test_people_changes_announce_people(app, asha):
    """Adding someone tells every page to refresh its people lists."""
    [topics] = _collect(
        app.state.hub,
        lambda: asha.post("/api/people", json={"name": "Neha Rao", "username": "neha"}),
        1,
    )
    assert topics == {"people"}
