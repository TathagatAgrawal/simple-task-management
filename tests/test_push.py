"""Tests for Web Push: who is pushed, when, and the API for turning alerts on for a device."""

import dataclasses
import json
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
from conftest import move, new_task, sign_in
from pywebpush import WebPushException, webpush

from simple_task_management import db, push, store
from simple_task_management.app import create_app

KEYS = {"p256dh": "BPubKey", "auth": "AuthSecret"}


class Recorder:
    """A stand-in for the push service: remembers each message and can fail on demand."""

    def __init__(self):
        """Start empty."""
        self.sent: list[tuple[str, dict]] = []
        self.fail: dict[str, Exception] = {}

    def __call__(self, subscription: dict, payload: str) -> None:
        """Record a message, or raise what the test asked for this device."""
        endpoint = subscription["endpoint"]
        if endpoint in self.fail:
            raise self.fail[endpoint]
        self.sent.append((endpoint, json.loads(payload)))


@pytest.fixture
def recorder(app):
    """Replace the app's sender with a recorder."""
    rec = Recorder()
    app.state.pusher.send = rec
    return rec


def _subscribe(conn, user_id: int, endpoint: str) -> None:
    """Give a person a device."""
    store.save_push_subscription(conn, user_id, endpoint, KEYS["p256dh"], KEYS["auth"])


def _run(app, conn) -> int:
    """Push whatever is waiting."""
    return app.state.pusher.run_once(conn)


def test_a_new_task_pushes_to_the_assignee_with_a_readable_banner(asha, app, conn, users, recorder):
    """Ravi's device gets the task title, who did what, and his unread count."""
    _subscribe(conn, users["ravi"], "https://push.example/ravi")
    new_task(asha, title="GSTR-3B for Mehta", assignee_ids=[users["ravi"]])
    assert _run(app, conn) == 1
    ((endpoint, message),) = recorder.sent
    assert endpoint == "https://push.example/ravi"
    assert message["title"] == "GSTR-3B for Mehta"
    assert message["body"] == "Asha Iyer assigned you a new task"
    assert message["sticky"] is True
    assert message["unread"] == 1
    assert message["tag"] == f"n-{message['id']}"


def test_a_notification_is_pushed_only_once(asha, app, conn, users, recorder):
    """Running again, or restarting, never repeats a push."""
    _subscribe(conn, users["ravi"], "https://push.example/ravi")
    new_task(asha, assignee_ids=[users["ravi"]])
    _run(app, conn)
    assert _run(app, conn) == 0
    assert len(recorder.sent) == 1


def test_the_person_who_made_the_change_is_not_pushed(asha, app, conn, users, recorder):
    """Asha moving her own task sends nothing to her phone, even with a device saved."""
    _subscribe(conn, users["asha"], "https://push.example/asha")
    task_id = new_task(asha, assignee_ids=[users["asha"], users["ravi"]])
    move(asha, task_id, "doing")
    _run(app, conn)
    assert recorder.sent == []


def test_the_creator_is_pushed_when_the_assignee_acts(asha, ravi, app, conn, users, recorder):
    """Asha gave Ravi a task; when Ravi marks it Done, Asha's phone buzzes."""
    _subscribe(conn, users["asha"], "https://push.example/asha")
    task_id = new_task(asha, assignee_ids=[users["ravi"]])
    _run(app, conn)
    move(ravi, task_id, "done")
    _run(app, conn)
    ((_, message),) = recorder.sent
    assert message["body"] == "Ravi Kumar marked this Done"


def test_only_alert_mode_is_pushed(asha, app, conn, users, recorder):
    """Bell-only and Nothing settings produce no push, and the row is still marked handled."""
    _subscribe(conn, users["ravi"], "https://push.example/ravi")
    store.set_notification_settings(conn, users["ravi"], {"assigned": "inbox"})
    new_task(asha, assignee_ids=[users["ravi"]])
    assert _run(app, conn) == 0
    assert recorder.sent == []
    assert (
        conn.execute("SELECT COUNT(*) FROM notifications WHERE pushed_at IS NULL").fetchone()[0]
        == 0
    )


def test_every_device_of_a_person_is_pushed(asha, app, conn, users, recorder):
    """A phone and a laptop both hear about the same change."""
    _subscribe(conn, users["ravi"], "https://push.example/phone")
    _subscribe(conn, users["ravi"], "https://push.example/laptop")
    new_task(asha, assignee_ids=[users["ravi"]])
    assert _run(app, conn) == 2
    assert sorted(e for e, _ in recorder.sent) == [
        "https://push.example/laptop",
        "https://push.example/phone",
    ]


def test_a_device_the_service_says_is_gone_is_forgotten(asha, app, conn, users, recorder):
    """A 404 or 410 removes that device and the others are still pushed."""
    _subscribe(conn, users["ravi"], "https://push.example/dead")
    _subscribe(conn, users["ravi"], "https://push.example/alive")
    recorder.fail["https://push.example/dead"] = push.PushGone()
    new_task(asha, assignee_ids=[users["ravi"]])
    assert _run(app, conn) == 1
    left = [r["endpoint"] for r in store.push_subscriptions_for(conn, users["ravi"])]
    assert left == ["https://push.example/alive"]


def test_a_failing_push_never_stops_the_others_or_repeats(asha, app, conn, users, recorder):
    """An unexpected error on one device is logged; other people still get theirs, once."""
    _subscribe(conn, users["ravi"], "https://push.example/broken")
    _subscribe(conn, users["meera"], "https://push.example/meera")
    recorder.fail["https://push.example/broken"] = RuntimeError("push service down")
    new_task(asha, assignee_ids=[users["ravi"], users["meera"]])
    assert _run(app, conn) == 1
    assert [e for e, _ in recorder.sent] == ["https://push.example/meera"]
    assert _run(app, conn) == 0
    assert len(store.push_subscriptions_for(conn, users["ravi"])) == 1  # kept: it may recover


def test_generic_banner_hides_the_task(asha, app, conn, users, recorder):
    """With task details off, the banner says only that a task changed."""
    _subscribe(conn, users["ravi"], "https://push.example/ravi")
    store.set_push_details(conn, users["ravi"], False)
    new_task(asha, title="Secret client matter", assignee_ids=[users["ravi"]])
    _run(app, conn)
    ((_, message),) = recorder.sent
    assert (message["title"], message["body"]) == ("Task Board", "A task changed")
    assert "Secret" not in json.dumps(message)


def test_old_notifications_are_marked_handled_but_not_sent(asha, app, conn, users, recorder):
    """After downtime, news older than ten minutes is not pushed late."""
    _subscribe(conn, users["ravi"], "https://push.example/ravi")
    new_task(asha, assignee_ids=[users["ravi"]])
    old = (db.datetime.now(db.UTC) - timedelta(minutes=30)).isoformat(timespec="seconds")
    conn.execute("UPDATE notifications SET created_at = ?", (old,))
    conn.commit()
    assert _run(app, conn) == 0
    assert recorder.sent == []
    assert (
        conn.execute("SELECT COUNT(*) FROM notifications WHERE pushed_at IS NULL").fetchone()[0]
        == 0
    )


def test_removed_people_are_not_pushed_and_lose_their_devices(asha, app, conn, users, recorder):
    """Removing someone deletes their devices."""
    _subscribe(conn, users["ravi"], "https://push.example/ravi")
    asha.delete(f"/api/people/{users['ravi']}")
    assert store.push_subscriptions_for(conn, users["ravi"]) == []


def test_the_update_marks_existing_notifications_handled(tmp_path):
    """Upgrading from version 5 never pushes old news, and people default to showing details."""
    conn = db.connect(tmp_path / "old.db")
    conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
    for step in db.MIGRATIONS[:4]:
        conn.executescript(step)
    conn.execute("PRAGMA user_version = 5")
    conn.execute(
        "INSERT INTO users (id, name, username, password_hash, is_active, created_at) "
        "VALUES (1, 'A', 'a', 'x', 1, '2026-11-10T04:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO notifications (user_id, task_title, body, kind, created_at) "
        "VALUES (1, 'T', 'moved this to Doing', 'moved', '2026-11-10T04:00:00+00:00')"
    )
    conn.commit()
    assert db.migrate(conn) == 6
    assert conn.execute("SELECT pushed_at FROM notifications").fetchone()[0] is not None
    assert conn.execute("SELECT push_details FROM users").fetchone()[0] == 1
    assert store.notifications_to_push(conn) == []


def test_the_signing_key_is_made_once_and_kept(conn):
    """The same key comes back every time, as the URL-safe text a browser expects."""
    first = push.public_key(conn)
    assert push.public_key(conn) == first
    assert len(first) == 87 and set(first) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )


def test_the_real_library_accepts_our_key_and_claims(conn, tmp_path, monkeypatch):
    """Encrypting for a genuine browser key with our signing key works (nothing is sent)."""
    import base64

    monkeypatch.chdir(tmp_path)  # the library's dry run leaves a scratch file in the folder
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    def b64(raw: bytes) -> str:
        """URL-safe base64 without padding, like a browser."""
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    browser = ec.generate_private_key(ec.SECP256R1())
    point = browser.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    info = {
        "endpoint": "https://web.push.apple.com/abc",
        "keys": {"p256dh": b64(point), "auth": b64(b"0123456789abcdef")},
    }
    out = webpush(
        info,
        '{"title": "x"}',
        vapid_private_key=push.load_key(conn),
        vapid_claims={"sub": "mailto:taskboard@example.com"},
        curl=True,
    )
    assert "web.push.apple.com" in out and "vapid" in out.lower()


def test_gone_answers_become_pushgone(conn, monkeypatch):
    """The real sender turns a 410 into PushGone and lets other failures through."""

    def fake(*args, **kwargs):
        """Pretend the push service answered with the code in ``status``."""
        raise WebPushException("nope", response=SimpleNamespace(status_code=status["code"]))

    status = {"code": 410}
    monkeypatch.setattr(push, "webpush", fake)
    send = push._web_sender(push.load_key(conn), "mailto:a@b.c")
    with pytest.raises(push.PushGone):
        send({"endpoint": "e", "keys": KEYS}, "{}")
    status["code"] = 500
    with pytest.raises(WebPushException):
        send({"endpoint": "e", "keys": KEYS}, "{}")


# ---------------------------------------------------------------- the API


@pytest.fixture
def on_app(settings, conn):
    """An app with Web Push switched on (its background loop runs once a client is open)."""
    return create_app(dataclasses.replace(settings, push_enabled=True))


def test_api_subscribe_check_and_unsubscribe(on_app, users, conn):
    """A device is saved, recognised, and removed; the key stays the same."""
    ravi = sign_in(on_app, "ravi")
    info = ravi.get("/api/push", params={"endpoint": "https://push.example/ravi"}).json()
    assert info["enabled"] and info["devices"] == 0 and not info["this_device"]
    assert info["details"] is True and len(info["public_key"]) == 87

    body = {"endpoint": "https://push.example/ravi", "keys": KEYS}
    assert ravi.put("/api/push/subscription", json=body).status_code == 204
    assert ravi.put("/api/push/subscription", json=body).status_code == 204  # harmless twice
    info = ravi.get("/api/push", params={"endpoint": "https://push.example/ravi"}).json()
    assert info["devices"] == 1 and info["this_device"] and info["public_key"]

    ravi.post("/api/push/unsubscribe", json={"endpoint": "https://push.example/ravi"})
    assert ravi.get("/api/push").json()["devices"] == 0


def test_api_people_cannot_remove_each_others_devices(on_app, users, conn):
    """Meera cannot unsubscribe Ravi's phone, and a device that signs in as someone else moves."""
    ravi = sign_in(on_app, "ravi")
    meera = sign_in(on_app, "meera")
    body = {"endpoint": "https://push.example/phone", "keys": KEYS}
    ravi.put("/api/push/subscription", json=body)
    meera.post("/api/push/unsubscribe", json={"endpoint": "https://push.example/phone"})
    assert ravi.get("/api/push").json()["devices"] == 1
    meera.put("/api/push/subscription", json=body)  # the phone is now Meera's
    assert ravi.get("/api/push").json()["devices"] == 0
    assert meera.get("/api/push").json()["devices"] == 1


def test_api_banner_choice_is_saved_per_person(on_app, users, conn):
    """Turning task details off affects only that person."""
    ravi = sign_in(on_app, "ravi")
    meera = sign_in(on_app, "meera")
    assert ravi.patch("/api/push", json={"details": False}).json()["details"] is False
    assert meera.get("/api/push").json()["details"] is True


def test_api_test_alert(on_app, users, conn):
    """The test button needs a device, then reaches every device of the person."""
    ravi = sign_in(on_app, "ravi")
    recorder = Recorder()
    on_app.state.pusher.send = recorder
    assert ravi.post("/api/push/test").status_code == 400
    ravi.put("/api/push/subscription", json={"endpoint": "https://push.example/a", "keys": KEYS})
    assert ravi.post("/api/push/test").json() == {"sent": 1}
    assert recorder.sent[0][1]["title"] == "Alerts are working"


def test_api_push_requires_sign_in_and_can_be_switched_off(app, users):
    """Signed-out callers are refused, and a server with push off says so."""
    from fastapi.testclient import TestClient

    assert TestClient(app).get("/api/push").status_code == 401
    ravi = sign_in(app, "ravi")
    info = ravi.get("/api/push").json()
    assert info["enabled"] is False and info["public_key"] == ""
    assert ravi.post("/api/push/test").status_code == 400


def test_the_background_loop_pushes_after_a_change(on_app, users, conn):
    """With the app running, a new task reaches the assignee's device within moments."""
    recorder = Recorder()
    on_app.state.pusher.send = recorder
    _subscribe(conn, users["ravi"], "https://push.example/ravi")
    asha = sign_in(on_app, "asha")
    new_task(asha, title="From the loop", assignee_ids=[users["ravi"]])
    deadline = time.monotonic() + 5
    while not recorder.sent and time.monotonic() < deadline:
        time.sleep(0.05)
    assert [m["title"] for _, m in recorder.sent] == ["From the loop"]
