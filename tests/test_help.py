"""Tests for the user manual page."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

import simple_task_management

STATIC = Path(simple_task_management.__file__).parent / "static"


def test_help_is_readable_before_signing_in(app, users):
    """The manual opens without a session and points back to sign-in."""
    with TestClient(app) as client:
        r = client.get("/help")
    assert r.status_code == 200
    assert "How to use Tasks" in r.text
    assert "Go to sign in" in r.text


def test_help_follows_the_signed_in_persons_theme(asha):
    """Signed in, the manual offers a way back and uses the person's theme."""
    asha.post("/me/theme", data={"theme": "dark"})
    html = asha.get("/help").text
    assert "Back to the board" in html
    assert '<html lang="en" data-theme="dark">' in html


def test_every_screenshot_in_the_manual_exists(asha):
    """Each annotated screenshot the manual references is shipped in static/help."""
    html = asha.get("/help").text
    images = re.findall(r'src="/static/help/([\w-]+\.jpg)', html)
    assert len(images) >= 9
    missing = [name for name in images if not (STATIC / "help" / name).is_file()]
    assert missing == []


def test_help_is_linked_from_the_app_and_login(app, asha, users):
    """The top bar and the sign-in screen both link to the manual."""
    assert 'href="/help"' in asha.get("/").text
    with TestClient(app) as client:
        assert 'href="/help"' in client.get("/").text
