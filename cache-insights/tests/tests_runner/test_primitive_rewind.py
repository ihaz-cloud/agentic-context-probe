"""Tests for cache_insights.tests_runner.primitive_rewind."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from cache_insights import nonce as nonce_mod
from cache_insights.tests_runner import primitive_rewind as runner


class _StubSession:
    def __init__(self, name: str = "stub"):
        self.name = name
        self.prompts: list[str] = []

    def baseline_mtime(self, **_):
        return None

    def send_prompt(self, text: str) -> None:
        self.prompts.append(text)

    def wait_for_completion(self, **_) -> Path:
        return Path("/tmp/fake-completion-path")


@contextmanager
def _stub_driver(vendor: str, **_) -> Iterator[_StubSession]:
    yield _StubSession(name="original")


@pytest.fixture
def stub_env(monkeypatch):
    monkeypatch.setattr(runner, "driver_ctx", _stub_driver)
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)
    fake_nonce = nonce_mod.Nonce(
        value="NONCE-VALUE", token_count=4096, vendor="anthropic",
        model="claude-test", seed="seed", is_verified=False,
    )
    monkeypatch.setattr(runner, "generate_nonce", lambda **_: fake_nonce)
    # Default: rewind succeeds silently (in-place).
    monkeypatch.setattr(runner, "rewind_session", lambda session, vendor, **_: None)


def _set_parser(monkeypatch, vendor: str, *usages: dict):
    calls = {"n": 0}

    def fake(*a, **kw):
        idx = calls["n"]
        calls["n"] += 1
        return usages[idx]
    monkeypatch.setitem(runner.VENDOR_PARSER, vendor, fake)


def test_anthropic_byte_identity_preserved(stub_env, monkeypatch):
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    post = {
        "input_tokens": 5005, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, post)

    result = runner.run_rewind_primitive("anthropic", "claude-test")
    assert result["verdict"] == "byte_identity_preserved"
    assert result["test_type"] == "rewind"
    assert [r["label"] for r in result["requests"]] == [
        "cold", "warm_baseline", "post_rewind",
    ]


def test_anthropic_byte_identity_broken_zero(stub_env, monkeypatch):
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    post = {
        "input_tokens": 5005, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, post)

    result = runner.run_rewind_primitive("anthropic", "claude-test")
    assert result["verdict"] == "byte_identity_broken"
    notes = result["notes"].lower()
    assert "did not preserve" in notes or "keystroke sequence" in notes
    assert "cli_version" in notes


def test_anthropic_byte_identity_broken_outside_tolerance(stub_env, monkeypatch):
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 5000,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    post = {
        "input_tokens": 5005, "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, post)

    result = runner.run_rewind_primitive("anthropic", "claude-test")
    assert result["verdict"] == "byte_identity_broken"
    assert "tolerance" in result["notes"].lower() or "partially" in result["notes"].lower()


def test_anthropic_contaminated(stub_env, monkeypatch):
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 4900, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    post = {
        "input_tokens": 5005, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, post)

    result = runner.run_rewind_primitive("anthropic", "claude-test")
    assert result["verdict"] == "contaminated"
    assert result["contaminated"] is True


def test_openai_skipped(stub_env, monkeypatch):
    """OpenAI: rewind raises RewindNotSupported → verdict=skipped, 2 requests."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm)

    def unsupported(session, vendor, **_):
        raise runner.RewindNotSupported(
            f"vendor {vendor!r} has no registered rewind primitive"
        )
    monkeypatch.setattr(runner, "rewind_session", unsupported)

    result = runner.run_rewind_primitive("openai", "gpt-test")
    assert result["verdict"] == "skipped"
    assert len(result["requests"]) == 2
    assert [r["label"] for r in result["requests"]] == ["cold", "warm_baseline"]
    assert "not registered" in result["notes"].lower()


def test_google_skipped(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    _set_parser(monkeypatch, "google", cold, warm)

    def unsupported(session, vendor, **_):
        raise runner.RewindNotSupported("no rewind for google")
    monkeypatch.setattr(runner, "rewind_session", unsupported)

    result = runner.run_rewind_primitive("google", "gemini-test")
    assert result["verdict"] == "skipped"
    assert len(result["requests"]) == 2


def test_verdict_error_on_rewind_failure(stub_env, monkeypatch):
    """Non-NotSupported RewindError → verdict=error (not skipped)."""
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm)

    def failing(session, vendor, **_):
        raise runner.RewindError("simulated rewind keystroke failure")
    monkeypatch.setattr(runner, "rewind_session", failing)

    result = runner.run_rewind_primitive("anthropic", "claude-test")
    assert result["verdict"] == "error"
    assert "RewindError" in result["error"] or "simulated rewind" in result["error"]
    assert len(result["requests"]) == 2


def test_verdict_error_on_post_rewind_parser_failure(stub_env, monkeypatch):
    """Parser failure on post_rewind turn → verdict=error, partial requests."""
    calls = {"n": 0}

    def fake(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "input_tokens": 5000, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 5000, "output_tokens": 5,
            }
        if calls["n"] == 2:
            return {
                "input_tokens": 5005, "cache_read_input_tokens": 4900,
                "cache_creation_input_tokens": 0, "output_tokens": 3,
            }
        raise ValueError("simulated parser failure on post_rewind")

    monkeypatch.setitem(runner.VENDOR_PARSER, "anthropic", fake)

    result = runner.run_rewind_primitive("anthropic", "claude-test")
    assert result["verdict"] == "error"
    assert "ValueError" in result["error"]
    assert len(result["requests"]) == 2


def test_verdict_error_on_driver_failure(monkeypatch):
    @contextmanager
    def failing_driver(vendor: str, **_):
        raise RuntimeError("tmux launch failed")
        yield  # pragma: no cover

    monkeypatch.setattr(runner, "driver_ctx", failing_driver)
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)
    fake_nonce = nonce_mod.Nonce(
        value="N", token_count=4096, vendor="anthropic",
        model="claude-test", seed="s", is_verified=False,
    )
    monkeypatch.setattr(runner, "generate_nonce", lambda **_: fake_nonce)

    result = runner.run_rewind_primitive("anthropic", "claude-test")
    assert result["verdict"] == "error"
    assert "RuntimeError" in result["error"]


def test_unknown_vendor_raises(stub_env):
    with pytest.raises(ValueError, match="Unknown vendor"):
        runner.run_rewind_primitive("not-a-vendor", "x")


def test_anthropic_field_mapping(stub_env, monkeypatch):
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4800,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    post = {
        "input_tokens": 5005, "cache_read_input_tokens": 4800,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, post)

    result = runner.run_rewind_primitive("anthropic", "claude-test")
    assert result["verdict"] == "byte_identity_preserved"
    assert result["requests"][2]["cached_tokens"] == 4800


def test_post_rewind_prompt_is_say_bravo(stub_env, monkeypatch):
    """Post-rewind sends 'say bravo' on the same (mutated) session."""
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4800,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    post = {
        "input_tokens": 5005, "cache_read_input_tokens": 4800,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, post)

    captured: list[str] = []

    class _CapturingSession(_StubSession):
        def send_prompt(self, text: str) -> None:
            captured.append(text)

    @contextmanager
    def _capturing_driver(vendor: str, **_):
        yield _CapturingSession()

    monkeypatch.setattr(runner, "driver_ctx", _capturing_driver)

    runner.run_rewind_primitive("anthropic", "claude-test")
    # Three send_prompt calls: nonce, "say alpha", "say bravo".
    assert captured[1] == "say alpha"
    assert captured[2] == "say bravo"


def test_result_passes_schema_validation(stub_env, monkeypatch):
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4800,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    post = {
        "input_tokens": 5005, "cache_read_input_tokens": 4800,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, post)

    result = runner.run_rewind_primitive("anthropic", "claude-test")
    assert result["vendor"] == "anthropic"
    assert result["test_type"] == "rewind"
    assert isinstance(result["nonce"], str)
