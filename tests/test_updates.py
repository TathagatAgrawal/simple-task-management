"""Tests for looking for updates on GitHub, and the admin settings around it."""

import asyncio
import contextlib
import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from simple_task_management import events, store, updates

GIT_ENV = {
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` (as a test author) and return what it printed."""
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **GIT_ENV},
    )
    return done.stdout.strip()


@pytest.fixture
def repos(tmp_path):
    """A pretend GitHub (``origin``), the firm's copy (``app``) and a developer's copy (``dev``)."""
    origin, app, dev = tmp_path / "origin.git", tmp_path / "app", tmp_path / "dev"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", str(origin), str(dev))
    (dev / "a.txt").write_text("one")
    git(dev, "add", ".")
    git(dev, "commit", "-m", "First version")
    git(dev, "push", "origin", "HEAD:main")
    git(tmp_path, "clone", str(origin), str(app))
    return {"origin": origin, "app": app, "dev": dev}


def publish(dev: Path, subject: str) -> None:
    """Make a new commit on the developer's copy and push it to the pretend GitHub."""
    (dev / "a.txt").write_text(subject)
    git(dev, "commit", "-am", subject)
    git(dev, "push", "origin", "HEAD:main")


def test_up_to_date_copy_is_not_behind(repos):
    """With nothing new on GitHub the copy is current."""
    status = updates.check(repos["app"])
    assert status.supported and status.error is None
    assert status.behind == 0 and status.commits == [] and status.current == status.latest


def test_new_commits_are_counted_and_described(repos):
    """New work on GitHub shows how many changes there are and what they were."""
    publish(repos["dev"], "Add notifications")
    publish(repos["dev"], "Fix the board")
    status = updates.check(repos["app"])
    assert status.behind == 2 and status.current != status.latest
    assert status.commits == ["Fix the board", "Add notifications"]


def test_looking_never_changes_the_installed_files(repos):
    """Checking only fetches: the working copy and its commit stay exactly as they were."""
    before = git(repos["app"], "rev-parse", "HEAD")
    publish(repos["dev"], "New thing")
    updates.check(repos["app"])
    assert git(repos["app"], "rev-parse", "HEAD") == before
    assert (repos["app"] / "a.txt").read_text() == "one"


def test_unreachable_github_is_explained_in_plain_words(repos):
    """If GitHub can't be reached the status says so instead of failing."""
    git(repos["app"], "remote", "set-url", "origin", str(repos["origin"]) + "-missing")
    status = updates.check(repos["app"])
    assert status.supported and "Couldn't reach GitHub" in status.error
    assert status.behind == 0 and status.current  # still knows what it is running


def test_a_folder_without_git_cannot_check(tmp_path):
    """A copy installed from a ZIP says it can't look, rather than pretending it is current."""
    status = updates.check(tmp_path)
    assert status.supported is False and "not installed with git" in status.error


def test_last_run_note_is_read_and_bad_notes_are_ignored(tmp_path):
    """The note update.ps1 leaves is shown; a missing or broken one is simply absent."""
    assert updates.read_last_run(tmp_path) is None
    note = tmp_path / updates.LAST_RUN_FILE
    note.write_text("not json", encoding="utf-8")
    assert updates.read_last_run(tmp_path) is None
    note.write_text(
        json.dumps({"ran_at": "2026-11-18T21:30:00+00:00", "result": "updated"}),
        encoding="utf-8-sig",
    )
    assert updates.read_last_run(tmp_path)["result"] == "updated"


# ------------------------------------------------------------ the admin API


@pytest.fixture
def isolated(app, tmp_path):
    """Point the app's update checker at an empty folder, so tests never reach for GitHub."""
    app.state.checker.app_dir = tmp_path
    return app.state.checker


def test_only_admins_see_or_change_update_settings(isolated, ravi):
    """Members get 403 on every update endpoint."""
    assert ravi.get("/api/update").status_code == 403
    assert ravi.post("/api/update/check").status_code == 403
    assert ravi.patch("/api/update", json={"auto_update": True}).status_code == 403


def test_update_info_before_any_check(isolated, asha):
    """Before the first look the admin sees the defaults: nothing available, auto-update off."""
    info = asha.get("/api/update").json()
    assert info["available"] is False and info["checked_at"] is None
    assert info["auto_update"] is False and info["last_run"] is None


def test_check_now_reports_what_is_waiting(app, asha, repos):
    """Checking now looks at GitHub and returns the changes that are waiting."""
    app.state.checker.app_dir = repos["app"]
    publish(repos["dev"], "A newer version")
    info = asha.post("/api/update/check").json()
    assert info["available"] is True and info["behind"] == 1
    assert info["commits"] == ["A newer version"] and info["checked_when"]
    assert asha.get("/api/update").json()["behind"] == 1  # remembered for the next visit


def test_auto_update_choice_is_saved_and_the_script_can_read_it(isolated, asha, settings, conn):
    """The toggle is stored, and the command the update script runs reports it."""
    from simple_task_management import cmd_update_setting

    assert asha.patch("/api/update", json={"auto_update": True}).json()["auto_update"] is True
    assert store.get_setting(conn, "auto_update") == "on"
    asha.patch("/api/update", json={"auto_update": False})
    assert store.get_setting(conn, "auto_update") == "off"
    asha.patch("/api/update", json={"auto_update": True})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_update_setting(None, settings)
    assert out.getvalue().strip() == "on"


def test_last_nightly_run_is_shown_to_admins(isolated, asha, settings):
    """What the nightly update did last time is part of the admin's update info."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / updates.LAST_RUN_FILE).write_text(
        json.dumps(
            {"ran_at": "2026-11-13T21:30:00+00:00", "result": "updated", "detail": "Now on abc1234"}
        ),
        encoding="utf-8",
    )
    last = asha.get("/api/update").json()["last_run"]
    assert last["result"] == "updated" and last["detail"] == "Now on abc1234" and last["when"]


def test_changes_to_update_settings_are_announced(app, isolated, asha):
    """Other admins' open pages refresh when the setting or the answer changes."""

    async def scenario() -> set[str]:
        queue = app.state.hub.subscribe()
        await asyncio.to_thread(lambda: asha.patch("/api/update", json={"auto_update": True}))
        return {await asyncio.wait_for(queue.get(), 2)}

    assert asyncio.run(scenario()) == {"updates"}


def test_the_background_check_repeats_and_tells_pages(monkeypatch, tmp_path):
    """The checker looks soon after start-up and tells open pages each time."""
    monkeypatch.setattr(updates, "FIRST_CHECK_DELAY_SECONDS", 0)
    checker = updates.Checker(tmp_path)
    hub = events.Hub()

    async def scenario() -> str | None:
        queue = hub.subscribe()
        task = asyncio.create_task(checker.loop(1, hub))
        topic = await asyncio.wait_for(queue.get(), 5)
        task.cancel()
        return topic

    assert asyncio.run(scenario()) == "updates"
    assert checker.status is not None and checker.status.supported is False
