"""Unit tests for cache_insights.driver.rewind.

No real subprocess or tmux invocation. ``session.send_keys`` is captured and
asserted directly.
"""

from __future__ import annotations

import pytest

from cache_insights.driver import rewind as rewind_mod
from cache_insights.driver.dispatch import VENDOR_LAUNCH


class _StubSession:
    def __init__(self):
        self.send_keys_calls: list[tuple] = []

    def send_keys(self, *keys: str) -> None:
        self.send_keys_calls.append(keys)


def test_unknown_vendor_raises_value_error():
    """Programming error: unknown vendor surfaces from get_launch_spec."""
    session = _StubSession()
    with pytest.raises(ValueError, match="Unknown vendor"):
        rewind_mod.rewind_session(session, "not-a-vendor")


def test_anthropic_sends_escape_escape_then_enter_enter(monkeypatch):
    """Anthropic: open menu (Esc-Esc), confirm (Enter, Enter)."""
    monkeypatch.setattr(rewind_mod.time, "sleep", lambda _: None)

    session = _StubSession()
    rewind_mod.rewind_session(session, "anthropic")

    # Expected: one send_keys for ("Escape", "Escape"), then two for "Enter".
    assert len(session.send_keys_calls) == 3
    assert session.send_keys_calls[0] == ("Escape", "Escape")
    assert session.send_keys_calls[1] == ("Enter",)
    assert session.send_keys_calls[2] == ("Enter",)


def test_openai_raises_rewind_not_supported(monkeypatch):
    monkeypatch.setattr(rewind_mod.time, "sleep", lambda _: None)
    session = _StubSession()
    with pytest.raises(rewind_mod.RewindNotSupported, match="rewind primitive"):
        rewind_mod.rewind_session(session, "openai")
    assert session.send_keys_calls == []


def test_google_raises_rewind_not_supported(monkeypatch):
    monkeypatch.setattr(rewind_mod.time, "sleep", lambda _: None)
    session = _StubSession()
    with pytest.raises(rewind_mod.RewindNotSupported):
        rewind_mod.rewind_session(session, "google")
    assert session.send_keys_calls == []


def test_anthropic_depth_greater_than_one_sends_down_arrows(monkeypatch):
    """depth=3 sends Esc-Esc, then 2 'Down' arrows, then Enter, Enter."""
    monkeypatch.setattr(rewind_mod.time, "sleep", lambda _: None)

    session = _StubSession()
    rewind_mod.rewind_session(session, "anthropic", depth=3)

    # Esc-Esc, Down, Down, Enter, Enter = 5 send_keys calls
    assert len(session.send_keys_calls) == 5
    assert session.send_keys_calls[0] == ("Escape", "Escape")
    assert session.send_keys_calls[1] == ("Down",)
    assert session.send_keys_calls[2] == ("Down",)
    assert session.send_keys_calls[3] == ("Enter",)
    assert session.send_keys_calls[4] == ("Enter",)


def test_send_keys_failure_wraps_as_rewind_error(monkeypatch):
    """Underlying tmux error is wrapped as RewindError (not RewindNotSupported)."""
    monkeypatch.setattr(rewind_mod.time, "sleep", lambda _: None)

    class BoomSession:
        def send_keys(self, *_):
            raise RuntimeError("tmux send-keys failed")

    with pytest.raises(rewind_mod.RewindError, match="RuntimeError"):
        rewind_mod.rewind_session(BoomSession(), "anthropic")


def test_rewind_not_supported_is_rewind_error_subclass():
    """Callers can catch the broader RewindError to handle both cases."""
    assert issubclass(rewind_mod.RewindNotSupported, rewind_mod.RewindError)


def test_rewind_keys_read_from_dispatch():
    """Verify rewind_keys snapshot in LaunchSpec matches what the helper uses."""
    assert VENDOR_LAUNCH["anthropic"].rewind_keys == ("Escape", "Escape")
    assert VENDOR_LAUNCH["openai"].rewind_keys is None
    assert VENDOR_LAUNCH["google"].rewind_keys is None
