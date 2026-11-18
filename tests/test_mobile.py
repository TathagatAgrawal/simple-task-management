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
    manifest = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
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


def test_the_built_client_is_shipped_with_the_package():
    """The committed bundle exists, so the production PC never needs Node."""
    bundle = STATIC / "dist" / "app.js"
    assert bundle.is_file() and bundle.stat().st_size > 10_000
    assert "/api/events" in bundle.read_text(encoding="utf-8")


def test_service_worker_is_served_from_the_root(app, users):
    """The service worker lives at /sw.js so its scope covers the whole site."""
    with TestClient(app) as client:
        r = client.get("/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "notificationclick" in r.text
