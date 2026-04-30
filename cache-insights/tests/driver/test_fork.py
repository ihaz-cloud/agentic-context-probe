"""Unit tests for cache_insights.driver.fork — vendor-agnostic fork helper.

No real subprocess, tmux, or vendor CLI is invoked. The fork mechanics are
exercised via mocks of subprocess.run, TmuxSession.launch, and Path.home.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cache_insights.driver import fork as fork_mod
from cache_insights.driver.dispatch import VENDOR_LAUNCH


class _StubSession:
    """Minimal TmuxSession stand-in.

    The fork helper only reads ``name``, ``spec``, ``working_dir``, and calls
    ``send_keys`` for the in-process Google flow. Cross-process flows
    construct a fresh ``TmuxSession`` (which we patch ``.launch`` on).
    """

    def __init__(self, vendor: str = "anthropic"):
        self.name = "orig"
        self.spec = VENDOR_LAUNCH[vendor]
        self.working_dir = Path("/tmp")
        self.send_keys_calls: list[tuple] = []

    def send_keys(self, *keys: str) -> None:
        self.send_keys_calls.append(keys)


def test_unknown_vendor_raises_fork_error():
    session = _StubSession()
    with pytest.raises(fork_mod.ForkError, match="Unknown vendor"):
        fork_mod.fork_session(session, "not-a-vendor")


def test_anthropic_fork_launches_with_resume_and_fork_session(monkeypatch, tmp_path):
    """anthropic: read newest jsonl stem, launch new tmux with --resume + --fork-session."""
    fake_home = tmp_path
    proj_dir = fake_home / ".claude" / "projects" / "fake-project"
    proj_dir.mkdir(parents=True)
    (proj_dir / "abc-123.jsonl").write_text("{}\n")
    monkeypatch.setattr(fork_mod.Path, "home", classmethod(lambda cls: fake_home))

    captured: list[tuple] = []

    def fake_launch(self_session, *extra_args):
        captured.append(extra_args)
    monkeypatch.setattr(fork_mod.TmuxSession, "launch", fake_launch)

    session = _StubSession(vendor="anthropic")
    forked = fork_mod.fork_session(session, "anthropic", fork_name="forked-1")

    assert forked.name == "forked-1"
    assert captured == [("--resume", "abc-123", "--fork-session")]


def test_anthropic_no_session_files_raises_fork_error(monkeypatch, tmp_path):
    fake_home = tmp_path
    (fake_home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setattr(fork_mod.Path, "home", classmethod(lambda cls: fake_home))

    session = _StubSession(vendor="anthropic")
    with pytest.raises(fork_mod.ForkError, match="no Claude session JSONL"):
        fork_mod.fork_session(session, "anthropic")


def test_anthropic_missing_projects_dir_raises_fork_error(monkeypatch, tmp_path):
    fake_home = tmp_path  # no .claude/projects exists
    monkeypatch.setattr(fork_mod.Path, "home", classmethod(lambda cls: fake_home))

    session = _StubSession(vendor="anthropic")
    with pytest.raises(fork_mod.ForkError, match="projects directory not found"):
        fork_mod.fork_session(session, "anthropic")


def test_openai_fork_launches_with_codex_fork(monkeypatch):
    """openai: read session id from `codex sessions list --json`, launch new tmux with `fork`."""
    sessions_list_output = json.dumps([{"id": "sess-abc"}])

    def mock_run(cmd, **_):
        if cmd[:3] == ["codex", "sessions", "list"]:
            return MagicMock(returncode=0, stdout=sessions_list_output, stderr="")
        raise AssertionError(f"Unexpected subprocess.run: {cmd}")
    monkeypatch.setattr(fork_mod.subprocess, "run", mock_run)

    captured: list[tuple] = []

    def fake_launch(self_session, *extra_args):
        captured.append(extra_args)
    monkeypatch.setattr(fork_mod.TmuxSession, "launch", fake_launch)

    session = _StubSession(vendor="openai")
    forked = fork_mod.fork_session(session, "openai", fork_name="forked-2")

    assert forked.name == "forked-2"
    assert captured == [("fork", "sess-abc")]


def test_openai_codex_list_failure_raises_fork_error(monkeypatch):
    def failing_run(cmd, **_):
        return MagicMock(returncode=1, stdout="", stderr="codex error: bad auth")
    monkeypatch.setattr(fork_mod.subprocess, "run", failing_run)

    session = _StubSession(vendor="openai")
    with pytest.raises(fork_mod.ForkError, match="codex sessions list failed"):
        fork_mod.fork_session(session, "openai")


def test_openai_codex_list_no_sessions_raises_fork_error(monkeypatch):
    def empty_run(cmd, **_):
        return MagicMock(returncode=0, stdout="[]", stderr="")
    monkeypatch.setattr(fork_mod.subprocess, "run", empty_run)

    session = _StubSession(vendor="openai")
    with pytest.raises(fork_mod.ForkError, match="no sessions"):
        fork_mod.fork_session(session, "openai")


def test_openai_codex_list_invalid_json_raises_fork_error(monkeypatch):
    def bad_run(cmd, **_):
        return MagicMock(returncode=0, stdout="not json", stderr="")
    monkeypatch.setattr(fork_mod.subprocess, "run", bad_run)

    session = _StubSession(vendor="openai")
    with pytest.raises(fork_mod.ForkError, match="non-JSON"):
        fork_mod.fork_session(session, "openai")


def test_openai_codex_list_missing_id_raises_fork_error(monkeypatch):
    def bad_shape_run(cmd, **_):
        return MagicMock(returncode=0, stdout=json.dumps([{"foo": "bar"}]), stderr="")
    monkeypatch.setattr(fork_mod.subprocess, "run", bad_shape_run)

    session = _StubSession(vendor="openai")
    with pytest.raises(fork_mod.ForkError, match="missing 'id'"):
        fork_mod.fork_session(session, "openai")


def test_google_fork_uses_in_process_resume_commands(monkeypatch):
    """google: in-process via /resume save + /resume resume; same session returned."""
    monkeypatch.setattr(fork_mod.time, "sleep", lambda _: None)

    session = _StubSession(vendor="google")
    forked = fork_mod.fork_session(session, "google", fork_name="my_tag")

    assert forked is session
    assert len(session.send_keys_calls) == 3
    delete_cmd = session.send_keys_calls[0][0]
    save_cmd = session.send_keys_calls[1][0]
    resume_cmd = session.send_keys_calls[2][0]
    assert delete_cmd == "/resume delete my_tag"
    assert save_cmd == "/resume save my_tag"
    assert resume_cmd == "/resume resume my_tag"


def test_google_fork_default_tag(monkeypatch):
    """google: when fork_name not provided, generates a fork_<timestamp> tag."""
    monkeypatch.setattr(fork_mod.time, "sleep", lambda _: None)

    session = _StubSession(vendor="google")
    fork_mod.fork_session(session, "google")

    save_cmd = session.send_keys_calls[1][0]
    assert save_cmd.startswith("/resume save fork_")


def test_unexpected_exception_wraps_as_fork_error(monkeypatch):
    """Non-ForkError exceptions inside the vendor fork path are wrapped."""
    def boom_run(cmd, **_):
        raise OSError("simulated OS error")
    monkeypatch.setattr(fork_mod.subprocess, "run", boom_run)

    session = _StubSession(vendor="openai")
    with pytest.raises(fork_mod.ForkError, match="OSError"):
        fork_mod.fork_session(session, "openai")
