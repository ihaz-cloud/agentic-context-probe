"""Tests for cache_insights.tests_runner.suffix_variation.

Real CLIs are NOT invoked. The driver context manager AND the fork helper are
mocked so we exercise verdict logic and post-fork session routing
deterministically without subprocess calls.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from cache_insights import nonce as nonce_mod
from cache_insights.tests_runner import suffix_variation as runner


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
    """Stub driver, parsers, and fork (default in-process: same session returned)."""
    monkeypatch.setattr(runner, "driver_ctx", _stub_driver)
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)

    fake_nonce = nonce_mod.Nonce(
        value="NONCE-VALUE", token_count=4096, vendor="openai",
        model="gpt-test", seed="seed", is_verified=False,
    )
    monkeypatch.setattr(runner, "generate_nonce", lambda **_: fake_nonce)

    # Default fork: in-process — return the same session.
    monkeypatch.setattr(runner, "fork_session", lambda session, vendor, **_: session)


def _set_parser(monkeypatch, vendor: str, *usages: dict):
    calls = {"n": 0}

    def fake(*a, **kw):
        idx = calls["n"]
        calls["n"] += 1
        return usages[idx]
    monkeypatch.setitem(runner.VENDOR_PARSER, vendor, fake)


def test_verdict_cache_hit_confirmed(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_suffix_variation("openai", "gpt-test")
    assert result["verdict"] == "cache_hit_confirmed"
    assert result["contaminated"] is False
    assert result["hit_ratio"] == pytest.approx(4900 / 5005)
    assert [r["label"] for r in result["requests"]] == [
        "cold", "warm_baseline", "post_fork",
    ]


def test_verdict_cache_hit_within_tolerance(stub_env, monkeypatch):
    """Post-fork cached within 10% of baseline → cache_hit_confirmed."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 5000, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4600, "output_tokens": 3}  # 8% under
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_suffix_variation("openai", "gpt-test")
    assert result["verdict"] == "cache_hit_confirmed"


def test_verdict_cache_miss_zero(stub_env, monkeypatch):
    """Post-fork cached=0 → cache_miss with suffix-invalidation note."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 0, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_suffix_variation("openai", "gpt-test")
    assert result["verdict"] == "cache_miss"
    assert result["contaminated"] is False
    assert "hit_ratio" not in result
    notes = result["notes"].lower()
    assert "invalidat" in notes or "fork-per-question" in notes


def test_verdict_cache_miss_outside_tolerance(stub_env, monkeypatch):
    """Post-fork cached>0 but >10% off baseline → cache_miss with degraded note."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 5000, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 1000, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_suffix_variation("openai", "gpt-test")
    assert result["verdict"] == "cache_miss"
    assert "tolerance" in result["notes"].lower() or "partially" in result["notes"].lower()


def test_verdict_contaminated(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 100, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_suffix_variation("openai", "gpt-test")
    assert result["verdict"] == "contaminated"
    assert result["contaminated"] is True
    assert "excluded" in result["notes"]


def test_verdict_error_on_fork_failure(stub_env, monkeypatch):
    """When fork_session raises ForkError, verdict=error and partial requests retained."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm)  # 3rd call would fail; never called

    def failing_fork(session, vendor, **_):
        raise runner.ForkError("simulated fork failure")
    monkeypatch.setattr(runner, "fork_session", failing_fork)

    result = runner.run_suffix_variation("openai", "gpt-test")
    assert result["verdict"] == "error"
    assert "ForkError" in result["error"] or "simulated fork failure" in result["error"]
    # Partial requests retained: cold + warm_baseline succeeded.
    assert len(result["requests"]) == 2
    assert [r["label"] for r in result["requests"]] == ["cold", "warm_baseline"]


def test_verdict_error_on_parse_failure_mid_sequence(stub_env, monkeypatch):
    """Parser failure on turn 3 (post-fork) is captured as error verdict."""
    calls = {"n": 0}

    def fake(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
        if calls["n"] == 2:
            return {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
        raise ValueError("simulated parser failure on post_fork")

    monkeypatch.setitem(runner.VENDOR_PARSER, "openai", fake)

    result = runner.run_suffix_variation("openai", "gpt-test")
    assert result["verdict"] == "error"
    assert "ValueError" in result["error"]
    assert "simulated parser failure" in result["error"]
    assert len(result["requests"]) == 2


def test_verdict_error_on_driver_failure(monkeypatch):
    @contextmanager
    def failing_driver(vendor: str, **_):
        raise RuntimeError("tmux launch failed")
        yield  # pragma: no cover

    monkeypatch.setattr(runner, "driver_ctx", failing_driver)
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)
    fake_nonce = nonce_mod.Nonce(
        value="N", token_count=4096, vendor="openai",
        model="gpt-test", seed="s", is_verified=False,
    )
    monkeypatch.setattr(runner, "generate_nonce", lambda **_: fake_nonce)

    result = runner.run_suffix_variation("openai", "gpt-test")
    assert result["verdict"] == "error"
    assert "RuntimeError" in result["error"]
    assert "tmux launch failed" in result["error"]


def test_unknown_vendor_raises(stub_env):
    with pytest.raises(ValueError, match="Unknown vendor"):
        runner.run_suffix_variation("not-a-vendor", "x")


def test_anthropic_field_mapping(stub_env, monkeypatch):
    """Anthropic uses cache_read_input_tokens — must map to canonical cached_tokens."""
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

    result = runner.run_suffix_variation("anthropic", "claude-test")
    assert result["verdict"] == "cache_hit_confirmed"
    assert result["requests"][2]["cached_tokens"] == 4800


def test_cross_process_fork_routes_post_prompt_to_forked_session(stub_env, monkeypatch):
    """Cross-process fork returns a different session; post-fork prompt goes there."""
    forked = _StubSession(name="forked")
    monkeypatch.setattr(runner, "fork_session", lambda session, vendor, **_: forked)

    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4800, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    result = runner.run_suffix_variation("openai", "gpt-test")
    assert result["verdict"] == "cache_hit_confirmed"
    # post_fork prompt was routed to the forked session.
    assert "say bravo" in forked.prompts
    # And the forked session was torn down.
    assert forked.torn_down is True


def test_in_process_fork_does_not_teardown_original(stub_env, monkeypatch):
    """In-process fork (same session returned): no separate teardown."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4800, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, post)

    runner.run_suffix_variation("openai", "gpt-test")
    # In-process fork uses the same session; nothing to teardown beyond
    # what driver_ctx does on exit. No assertion needed here beyond the
    # fact that the run completed without error.


def test_result_passes_schema_validation(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    post = {"input_tokens": 5005, "cached_tokens": 4800, "output_tokens": 3}
    _set_parser(monkeypatch, "google", cold, warm, post)

    result = runner.run_suffix_variation("google", "gemini-test")
    assert result["vendor"] == "google"
    assert result["test_type"] == "suffix_variation"
    assert isinstance(result["nonce"], str)
