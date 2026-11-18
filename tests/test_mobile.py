"""Tests for the phone layout and the installable-web-app pieces (manifest, icons, meta tags)."""

import json
import struct
from pathlib import Path

from fastapi.testclient import TestClient

import simple_task_management

STATIC = Path(simple_task_management.__file__).parent / "static"


def png_size(path: Path) -> tuple[int, int]:
    """Width and height read from a PNG file's header."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_manifest_makes_the_app_installable(app, users):
    """The manifest opens full-screen from the root and needs no sign-in."""
    with TestClient(app) as client:
        r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    manifest = r.json()
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert {i["sizes"] for i in manifest["icons"]} >= {"192x192", "512x512"}
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])


def test_every_manifest_icon_exists_at_its_stated_size():
    """Each icon in the manifest is a real PNG of the size it claims."""
    manifest = json.loads((STATIC / "manifest.webmanifest").read_text())
    for icon in manifest["icons"]:
        width, height = png_size(STATIC / icon["src"].removeprefix("/static/"))
        assert f"{width}x{height}" == icon["sizes"]
    assert png_size(STATIC / "icons" / "apple-touch-icon.png") == (180, 180)


def test_page_has_the_home_screen_tags(asha):
    """The page links the manifest and icon and asks iOS for a full-screen web app."""
    html = asha.get("/").text
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png"' in html
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html
    assert "viewport-fit=cover" in html


def test_signed_in_page_has_tabs_and_a_me_view(asha):
    """Phones get a tab bar and a Me tab holding what the user menu has on desktop."""
    html = asha.get("/").text
    assert 'data-tab="board" data-seg="todo"' in html
    for tab in ("board", "soon", "me"):
        assert f"tbSetTab('{tab}')" in html
    assert 'id="me-view"' in html
    assert "Change password" in html


def test_signed_out_page_has_no_tabs(app, users):
    """The login screen is not a tabbed app."""
    with TestClient(app) as client:
        html = client.get("/").text
    assert "data-tab" not in html
    assert 'class="tabbar"' not in html


def test_board_fragment_has_status_tabs_and_swipeable_cards(asha):
    """The board offers a status control with counts and wraps each card for swiping."""
    asha.post("/tasks", data={"title": "File GSTR-3B", "due": "2026-11-20"})
    html = asha.get("/board", params={"who": "all"}).text
    for status in ("todo", "doing", "done"):
        assert f"tbSetSeg('{status}')" in html
    assert 'class="card-wrap"' in html
    assert 'class="swipe-hint"' in html


def test_summary_fragment_reports_the_overdue_count(asha):
    """The summary carries the overdue count the Coming up tab badge shows."""
    asha.post("/tasks", data={"title": "Late filing", "due": "2026-11-01"})
    html = asha.get("/summary", params={"who": "all"}).text
    assert 'data-overdue="1"' in html
