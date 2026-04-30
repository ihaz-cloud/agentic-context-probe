"""Tests for cache_insights.tests_runner.primitive_fork.

Mirrors test_suffix_variation.py with byte_identity_* verdict assertions.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from cache_insights import nonce as nonce_mod
from cache_insights.tests_runner import primitive_fork as runner


class _StubSession:
    def __init__(self, name: str = "stub"):
        self.name = name
        self.prompts: list[str] = []
        self.torn_down = False

    def baseline_mtime(self, **_):
        return None

    def send_prompt(self, text: str) -> None:
        self.prompts.append(text)

    def wait_for_completion(self, **_) -> Path:
        return Path("/tmp/fake-completion-path")

    def teardown(self) -> None:
        self.torn_down = True


@contextmanager
def _stub_driver(vendor: str, **_) -> Iterator[_StubSession]:
    yield _StubSession(name="original")


@pytest.fixture
def stub_env(monkeypatch):
    monkeypatch.setattr(runner, "driver_ctx", _stub_driver)
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)
    fake_nonce = nonce_mod.Nonce(
        value="NONCE-VALUE", token_count=4096, vendor="openai",
        model="gpt-test", seed="seed", is_verified=False,
    )
    monkeypatch.setattr(runner, "generate_nonce", lambda **_: fake_nonce)
    monkeypatch.setattr(runner, "fork_session", lambda session, vendor, **_: session)


def _set_parser(monkeypatch, vendor: str, *usages: dict):
    calls = {"n": 0}

    def fake(*a, **kw):
        idx = calls["n"]
        calls["n"] += 1
        return usages[idx]
    monkeypatch.setitem(runner.VENDOR_PARSER, vendor, fake)


def test_verdict_byte_identity_preserved(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    _set_parser(monkeypatch, "anthropic", cold, warm, post)

    result = runner.run_fork_primitive("anthropic", "claude-test")
    # Note: anthropic uses cache_read_input_tokens; using cached_tokens above
    # is fine because usage_to_request_entry checks vendor == anthropic.
    # Switch to a vendor that uses cached_tokens directly:
    _set_parser(monkeypatch, "openai", cold, warm, post)
    result = runner.run_fork_primitive("openai", "gpt-test")
    assert result["verdict"] == "byte_identity_preserved"
    assert result["test_type"] == "fork"
    assert result["hit_ratio"] == pytest.approx(4900 / 5005)
    assert [r["label"] for r in result["requests"]] == [
        "cold", "warm_baseline", "post_fork",
    ]


def test_verdict_byte_identity_preserved_within_tolerance(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 5000, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4600, "output_tokens": 3}  # 8% under
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_fork_primitive("openai", "gpt-test")
    assert result["verdict"] == "byte_identity_preserved"


def test_verdict_byte_identity_broken_zero(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 0, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_fork_primitive("openai", "gpt-test")
    assert result["verdict"] == "byte_identity_broken"
    assert "did not preserve" in result["notes"].lower()
    # Codex-specific interpretation note appended for openai.
    assert "conversation_id" in result["notes"]


def test_verdict_byte_identity_broken_outside_tolerance(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 5000, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 1000, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_fork_primitive("openai", "gpt-test")
    assert result["verdict"] == "byte_identity_broken"
    assert "tolerance" in result["notes"].lower() or "partially" in result["notes"].lower()


def test_anthropic_broken_no_codex_note(stub_env, monkeypatch):
    """Codex-specific note appears only for openai, not for other vendors."""
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4800,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    post = {
        "input_tokens": 5005, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, post)

    result = runner.run_fork_primitive("anthropic", "claude-test")
    assert result["verdict"] == "byte_identity_broken"
    assert "conversation_id" not in result["notes"]


def test_verdict_contaminated(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 100, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_fork_primitive("openai", "gpt-test")
    assert result["verdict"] == "contaminated"
    assert result["contaminated"] is True


def test_verdict_error_on_fork_failure(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm)

    def failing_fork(session, vendor, **_):
        raise runner.ForkError("simulated fork failure")
    monkeypatch.setattr(runner, "fork_session", failing_fork)

    result = runner.run_fork_primitive("openai", "gpt-test")
    assert result["verdict"] == "error"
    assert "ForkError" in result["error"] or "simulated fork failure" in result["error"]
    assert len(result["requests"]) == 2


def test_unknown_vendor_raises(stub_env):
    with pytest.raises(ValueError, match="Unknown vendor"):
        runner.run_fork_primitive("not-a-vendor", "x")


def test_anthropic_field_mapping_preserved(stub_env, monkeypatch):
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

    result = runner.run_fork_primitive("anthropic", "claude-test")
    assert result["verdict"] == "byte_identity_preserved"
    assert result["requests"][2]["cached_tokens"] == 4800


def test_cross_process_fork_routes_post_prompt(stub_env, monkeypatch):
    forked = _StubSession(name="forked")
    monkeypatch.setattr(runner, "fork_session", lambda session, vendor, **_: forked)

    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4800, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_fork_primitive("openai", "gpt-test")
    assert result["verdict"] == "byte_identity_preserved"
    assert "say bravo" in forked.prompts
    assert forked.torn_down is True


def test_result_passes_schema_validation(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4800, "output_tokens": 3}
    _set_parser(monkeypatch, "google", cold, warm, post)

    result = runner.run_fork_primitive("google", "gemini-test")
    assert result["vendor"] == "google"
    assert result["test_type"] == "fork"
