"""Tests for cache_insights.driver.tmux.

All tests mock subprocess.run via monkeypatch so no real tmux session is
created. Completion polling tests are timeout-bounded.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from cache_insights.driver import tmux as tmux_mod
from cache_insights.driver.dispatch import LaunchSpec


class _FakeTmuxRecorder:
    """Records every tmux subcommand. Returns CompletedProcess with returncode 0
    by default; tests can override per-command results."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.responses: dict[str, subprocess.CompletedProcess] = {}

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
        assert cmd[0] == "tmux"
        sub = tuple(cmd[1:])
        self.calls.append(sub)
        # Pick an override by the first arg (e.g. "has-session", "load-buffer").
        key = sub[0] if sub else ""
        if key in self.responses:
            return self.responses[key]
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


@pytest.fixture
def fake_tmux(monkeypatch):
    rec = _FakeTmuxRecorder()
    monkeypatch.setattr(tmux_mod.subprocess, "run", rec)
    return rec


def _spec(name: str = "test", completion_path: Path | None = None) -> LaunchSpec:
    """Build a minimal LaunchSpec for tests."""
    return LaunchSpec(
        vendor="testvendor",
        binary="testbin",
        default_args=(),
        completion_source=lambda **_: completion_path or Path("/nonexistent"),
        completion_check=lambda p: p.exists() and p.stat().st_size > 0,
        compact_command="/test",
        rewind_keys=None,
    )


def test_session_exists_true(fake_tmux: _FakeTmuxRecorder):
    fake_tmux.responses["has-session"] = subprocess.CompletedProcess([], returncode=0)
    s = tmux_mod.TmuxSession("s1", _spec())
    assert s.exists() is True


def test_session_exists_false(fake_tmux: _FakeTmuxRecorder):
    fake_tmux.responses["has-session"] = subprocess.CompletedProcess([], returncode=1)
    s = tmux_mod.TmuxSession("s1", _spec())
    assert s.exists() is False


def test_launch_creates_new_session(fake_tmux: _FakeTmuxRecorder, tmp_path: Path):
    fake_tmux.responses["has-session"] = subprocess.CompletedProcess([], returncode=1)
    s = tmux_mod.TmuxSession("s1", _spec(), working_dir=tmp_path)
    s.launch("--extra", "flag")
    # Look for the new-session call.
    new_session_calls = [c for c in fake_tmux.calls if c[0] == "new-session"]
    assert len(new_session_calls) == 1
    args = new_session_calls[0]
    assert "s1" in args
    assert "testbin" in args
    assert "--extra" in args


def test_launch_raises_when_session_exists(fake_tmux: _FakeTmuxRecorder):
    fake_tmux.responses["has-session"] = subprocess.CompletedProcess([], returncode=0)
    s = tmux_mod.TmuxSession("s1", _spec())
    with pytest.raises(tmux_mod.TmuxError, match="already exists"):
        s.launch()


def test_send_prompt_sequence(fake_tmux: _FakeTmuxRecorder):
    fake_tmux.responses["has-session"] = subprocess.CompletedProcess([], returncode=0)
    s = tmux_mod.TmuxSession("s1", _spec())
    s.send_prompt("hello world")
    sub_cmds = [c[0] for c in fake_tmux.calls]
    # Expect: has-session, load-buffer, paste-buffer, send-keys (Enter)
    assert "load-buffer" in sub_cmds
    assert "paste-buffer" in sub_cmds
    assert "send-keys" in sub_cmds
    # Order: load-buffer must come before paste-buffer; paste-buffer before send-keys
    lb_idx = sub_cmds.index("load-buffer")
    pb_idx = sub_cmds.index("paste-buffer")
    sk_idx = sub_cmds.index("send-keys")
    assert lb_idx < pb_idx < sk_idx


def test_send_prompt_raises_when_session_missing(fake_tmux: _FakeTmuxRecorder):
    fake_tmux.responses["has-session"] = subprocess.CompletedProcess([], returncode=1)
    s = tmux_mod.TmuxSession("s1", _spec())
    with pytest.raises(tmux_mod.TmuxError, match="not running"):
        s.send_prompt("hi")


def test_send_keys_passes_through(fake_tmux: _FakeTmuxRecorder):
    fake_tmux.responses["has-session"] = subprocess.CompletedProcess([], returncode=0)
    s = tmux_mod.TmuxSession("s1", _spec())
    s.send_keys("Escape", "Escape")
    sk_calls = [c for c in fake_tmux.calls if c[0] == "send-keys"]
    assert len(sk_calls) == 1
    assert "Escape" in sk_calls[0]


def test_teardown_kills_existing_session(fake_tmux: _FakeTmuxRecorder):
    fake_tmux.responses["has-session"] = subprocess.CompletedProcess([], returncode=0)
    s = tmux_mod.TmuxSession("s1", _spec())
    s.teardown()
    kill_calls = [c for c in fake_tmux.calls if c[0] == "kill-session"]
    assert len(kill_calls) == 1


def test_baseline_mtime_returns_none_for_missing_file():
    s = tmux_mod.TmuxSession("s1", _spec(completion_path=Path("/nonexistent/missing")))
    assert s.baseline_mtime() is None


def test_baseline_mtime_returns_float_for_existing(tmp_path: Path):
    target = tmp_path / "completion.log"
    target.write_text("data")
    s = tmux_mod.TmuxSession("s1", _spec(completion_path=target))
    mt = s.baseline_mtime()
    assert isinstance(mt, float)


def test_wait_for_completion_succeeds_immediately(tmp_path: Path):
    """If file exists, has size, and check returns True, return path on first poll."""
    target = tmp_path / "done.log"
    target.write_text("ready")
    s = tmux_mod.TmuxSession("s1", _spec(completion_path=target))
    p = s.wait_for_completion(baseline_mtime=None, timeout=1.0, poll_interval=0.01)
    assert p == target


def test_wait_for_completion_timeout(tmp_path: Path):
    """If file never appears, raise CompletionTimeout."""
    s = tmux_mod.TmuxSession(
        "s1", _spec(completion_path=tmp_path / "never.log")
    )
    with pytest.raises(tmux_mod.CompletionTimeout):
        s.wait_for_completion(baseline_mtime=None, timeout=0.2, poll_interval=0.05)


def test_wait_for_completion_respects_baseline_mtime(tmp_path: Path):
    """A file existing pre-baseline must not satisfy the check."""
    target = tmp_path / "stale.log"
    target.write_text("old")
    baseline = target.stat().st_mtime + 100  # baseline far in the future
    s = tmux_mod.TmuxSession("s1", _spec(completion_path=target))
    with pytest.raises(tmux_mod.CompletionTimeout):
        s.wait_for_completion(baseline_mtime=baseline, timeout=0.2, poll_interval=0.05)
