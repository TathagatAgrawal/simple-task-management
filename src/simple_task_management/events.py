"""Live updates: tells every open page when something changed, so it can refresh at once.

Pages hold one Server-Sent Events connection (``GET /api/events``). Whenever a request changes
data, the route calls ``Hub.publish`` with a topic ("tasks", "notifications" or "people") and
each page refetches what it shows for that topic. There is nothing to store or replay: a page that
was disconnected simply refetches everything when it reconnects. The hub lives in this process,
which is fine because the app runs as a single process.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

TOPICS = ("tasks", "notifications", "people", "updates")
HEARTBEAT_SECONDS = 25.0  # keeps proxies from closing a quiet connection


class Hub:
    """Fans a topic out to every connected page. ``publish`` is safe to call from any thread."""

    def __init__(self) -> None:
        """Start with nobody connected."""
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[str | None]]] = set()

    def subscribe(self) -> asyncio.Queue[str | None]:
        """Register the calling page (must run inside the event loop) and return its queue."""
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._subscribers.add((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str | None]) -> None:
        """Forget a page that disconnected."""
        self._subscribers = {(loop, q) for loop, q in self._subscribers if q is not queue}

    def publish(self, *topics: str) -> None:
        """Tell every connected page that these topics changed."""
        for loop, queue in list(self._subscribers):
            for topic in topics:
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, topic)
                except RuntimeError:  # that page's event loop has already shut down
                    self.unsubscribe(queue)

    def close(self) -> None:
        """End every open stream (used at shutdown)."""
        for loop, queue in list(self._subscribers):
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(queue.put_nowait, None)


async def stream(hub: Hub, heartbeat: float = HEARTBEAT_SECONDS) -> AsyncIterator[str]:
    """The body of one page's event stream, as Server-Sent Events text.

    Each message is ``data: ["tasks", "notifications"]``, the topics that changed since the last
    one (several quick changes are merged into a single message). ``: ping`` comments keep the
    connection open when nothing happens. The ``ready`` message tells the page it is connected, so
    it can catch up on anything it missed while it wasn't.
    """
    queue = hub.subscribe()
    try:
        yield 'retry: 3000\n\ndata: ["ready"]\n\n'
        while True:
            try:
                first = await asyncio.wait_for(queue.get(), heartbeat)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if first is None:
                return
            topics = {first}
            while not queue.empty():
                more = queue.get_nowait()
                if more is None:
                    return
                topics.add(more)
            yield f"data: {json.dumps(sorted(topics))}\n\n"
    finally:
        hub.unsubscribe(queue)
