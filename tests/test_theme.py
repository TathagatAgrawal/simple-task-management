"""Tests for the per-person theme setting."""

from conftest import sign_in


def test_theme_is_saved_and_rendered(asha):
    """Choosing dark puts data-theme on <html>; System removes it."""
    assert "data-theme" not in asha.get("/").text.split(">")[1]
    r = asha.patch("/api/me", json={"theme": "dark"})
    assert r.status_code == 200 and r.json()["theme"] == "dark"
    assert '<html lang="en" data-theme="dark">' in asha.get("/").text
    asha.patch("/api/me", json={"theme": "system"})
    assert '<html lang="en">' in asha.get("/").text


def test_theme_follows_the_person_not_the_browser(app, asha):
    """A theme set in one session shows in a new session for the same person."""
    asha.patch("/api/me", json={"theme": "light"})
    other = sign_in(app, "asha")
    assert 'data-theme="light"' in other.get("/").text
    assert other.get("/api/me").json()["theme"] == "light"


def test_unknown_theme_rejected(asha):
    """Only system, light and dark are allowed."""
    assert asha.patch("/api/me", json={"theme": "pink"}).status_code == 400
