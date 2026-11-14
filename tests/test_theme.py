"""Tests for the per-person theme setting."""


def test_theme_is_saved_and_rendered(asha):
    """Choosing dark puts data-theme on <html>; System removes it."""
    assert "data-theme" not in asha.get("/").text.split(">")[1]
    assert asha.post("/me/theme", data={"theme": "dark"}).status_code == 204
    assert '<html lang="en" data-theme="dark">' in asha.get("/").text
    asha.post("/me/theme", data={"theme": "system"})
    assert '<html lang="en">' in asha.get("/").text


def test_theme_follows_the_person_not_the_browser(app, asha):
    """A theme set in one session shows in a new session for the same person."""
    from conftest import sign_in

    asha.post("/me/theme", data={"theme": "light"})
    other = sign_in(app, "asha")
    assert 'data-theme="light"' in other.get("/").text


def test_unknown_theme_rejected(asha):
    """Only system, light and dark are allowed."""
    assert asha.post("/me/theme", data={"theme": "pink"}).status_code == 400
