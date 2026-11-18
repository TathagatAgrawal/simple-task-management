"""Web Push: alerts that reach a phone or computer even when the board is closed.

A notification is written to the database as always (``store._notify``). Afterwards this module
finds the ones nobody has been pushed about yet, and posts a short encrypted message to every
device the person turned alerts on for. Apple, Google or Mozilla's push service wakes the device,
and the service worker (``static/sw.js``) shows it. Sending never happens inside the task's
transaction, so a push problem can never lose or block a change: failures are logged and skipped.

The app proves who it is to the push services with a key pair made once and kept in the
``app_settings`` table, so backups carry it and moving to a new PC keeps every device working.
"""

import asyncio
import base64
import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

from . import store
from .config import Settings
from .db import connect, now_iso
from .events import Hub

log = logging.getLogger(__name__)

KEY_SETTING = "vapid_private_key"
SAFETY_SECONDS = 30  # look for unsent notifications this often even if nothing woke us
GENERIC_TITLE = "Task Board"
GENERIC_BODY = "A task changed"

# Delivers one message: (subscription as the browser gave it, JSON text). Raises ``PushGone`` when
# the device no longer exists. Tests replace it with a recorder.
Sender = Callable[[dict, str], None]


class PushGone(Exception):
    """The push service says this device is gone for good (it answered 404 or 410)."""


def load_key(conn: sqlite3.Connection) -> Vapid:
    """The app's signing key, made and saved the first time it is needed."""
    pem = store.get_setting(conn, KEY_SETTING)
    if pem:
        return Vapid.from_pem(pem.encode())
    key = Vapid()
    key.generate_keys()
    store.set_setting(conn, KEY_SETTING, key.private_pem().decode())
    return key


def public_key(conn: sqlite3.Connection) -> str:
    """The key the browser needs to subscribe, as URL-safe base64 without padding."""
    raw = load_key(conn).public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _web_sender(key: Vapid, contact: str) -> Sender:
    """A sender that really posts to the push service, signing with ``key``."""

    def send(subscription: dict, payload: str) -> None:
        """Post one encrypted message; turn "gone" answers into ``PushGone``."""
        try:
            webpush(
                subscription,
                payload,
                vapid_private_key=key,
                vapid_claims={"sub": contact},
                ttl=3600,
                timeout=10,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                raise PushGone from exc
            raise

    return send


def _payload(row: sqlite3.Row, unread: int) -> str:
    """The message for one notification, as JSON for the service worker."""
    if row["push_details"]:
        title = row["title"]
        text = f"{row['actor_name'] or 'Someone'} {row['body']}"
    else:
        title, text = GENERIC_TITLE, GENERIC_BODY
    return json.dumps(
        {
            "id": row["id"],
            "tag": f"n-{row['id']}",
            "title": title,
            "body": text,
            "task_id": row["task_id"],
            "sticky": store.is_sticky(row["kind"], row["body"]),
            "unread": unread,
        }
    )


class Pusher:
    """Sends pushes for new notifications, in the background."""

    def __init__(self, settings: Settings) -> None:
        """Remember the settings. ``send`` is replaced by tests; None means really send."""
        self.settings = settings
        self.send: Sender | None = None

    def _sender(self, conn: sqlite3.Connection) -> Sender:
        """The sender to use now."""
        return self.send or _web_sender(load_key(conn), self.settings.push_contact)

    def _deliver(self, conn: sqlite3.Connection, user_id: int, payload: str) -> int:
        """Send one message to each of a person's devices; returns how many were reached."""
        subs = store.push_subscriptions_for(conn, user_id)
        if not subs:
            return 0
        send = self._sender(conn)
        reached = 0
        for sub in subs:
            info = {
                "endpoint": sub["endpoint"],
                "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
            }
            try:
                send(info, payload)
                reached += 1
            except PushGone:
                store.delete_push_subscription(conn, sub["endpoint"])
            except Exception:
                log.exception("Push to one device failed")
        return reached

    def run_once(self, conn: sqlite3.Connection, now: datetime | None = None) -> int:
        """Push every notification that is waiting; returns how many messages were sent."""
        pending = store.notifications_to_push(conn)
        if not pending:
            return 0
        oldest = (now or datetime.fromisoformat(now_iso())) - timedelta(
            minutes=store.PUSH_MAX_AGE_MINUTES
        )
        sent = 0
        for row in pending:
            fresh = datetime.fromisoformat(row["created_at"]) >= oldest
            if row["announce"] and row["is_active"] and fresh:
                unread = store.notification_counts(conn, row["user_id"])[0]
                sent += self._deliver(conn, row["user_id"], _payload(row, unread))
        store.mark_pushed(conn, [r["id"] for r in pending])
        return sent

    def send_test(self, conn: sqlite3.Connection, user_id: int) -> int:
        """Send a sample message to the person's own devices; returns how many were reached."""
        unread = store.notification_counts(conn, user_id)[0]
        payload = json.dumps(
            {
                "id": "test",
                "tag": "n-test",
                "title": "Alerts are working",
                "body": "You'll see this when a task of yours changes.",
                "task_id": None,
                "sticky": False,
                "unread": unread,
            }
        )
        return self._deliver(conn, user_id, payload)

    def _pass(self, db_path: Path) -> None:
        """One pass in its own connection; every failure is logged, never raised."""
        try:
            conn = connect(db_path)
            try:
                self.run_once(conn)
            finally:
                conn.close()
        except Exception:
            log.exception("Push pass failed")

    async def loop(self, hub: Hub) -> None:
        """Push whenever the hub says notifications changed, and every so often regardless."""
        queue = hub.subscribe()
        try:
            await asyncio.to_thread(self._pass, self.settings.db_path)
            while True:
                try:
                    topic = await asyncio.wait_for(queue.get(), SAFETY_SECONDS)
                except TimeoutError:
                    topic = "notifications"
                if topic is None:
                    return
                if topic == "notifications":
                    await asyncio.to_thread(self._pass, self.settings.db_path)
        finally:
            hub.unsubscribe(queue)
