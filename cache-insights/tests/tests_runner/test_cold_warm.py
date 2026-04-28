"""Tests for cache_insights.tests_runner.cold_warm.

Real CLIs are NOT invoked. The driver context manager is mocked to yield a
stub session whose send_prompt / wait_for_completion / baseline_mtime are
no-ops returning controlled paths. The vendor-specific parse_last_turn is
patched to return controlled usage dicts so we exercise verdict logic
deterministically.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from cache_insights import nonce as nonce_mod
from cache_insights.tests_runner import cold_warm as runner


class _StubSession:
    def __init__(self):
        self.prompts: list[str] = []

    def baseline_mtime(self, **_):
        return None

    def send_prompt(self, text: str) -> None:
        self.prompts.append(text)

    def wait_for_completion(self, **_) -> Path:
        return Path("/tmp/fake-completion-path")


@contextmanager
def _stub_driver(vendor: str, **_) -> Iterator[_StubSession]:
    yield _StubSession()


@pytest.fixture
def stub_env(monkeypatch):
    """Stub the driver context manager and vendor parsers; deterministic nonce."""
    # Stub the driver context manager.
    monkeypatch.setattr(runner, "driver_ctx", _stub_driver)

    # Stub get_launch_spec — only called for its side effects, return None ok
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)

    # Stub generate_nonce so tests don't hit any vendor API or fixture file.
    fake_nonce = nonce_mod.Nonce(
        value="NONCE-VALUE",
        token_count=4096,
        vendor="openai",
        model="gpt-test",
        seed="seed",
        is_verified=False,
    )
    monkeypatch.setattr(runner, "generate_nonce", lambda **_: fake_nonce)


def _set_parser(monkeypatch, vendor: str, cold: dict, warm: dict):
    """Install a parser that returns `cold` on first call, `warm` on second."""
    calls = {"n": 0}

    def fake(*a, **kw):
        calls["n"] += 1
        return cold if calls["n"] == 1 else warm
    monkeypatch.setitem(runner.VENDOR_PARSER, vendor, fake)


def test_verdict_cache_hit_confirmed(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5, "model": "gpt-x"}
    warm = {"input_tokens": 5000, "cached_tokens": 4900, "output_tokens": 5, "model": "gpt-x"}
    _set_parser(monkeypatch, "openai", cold, warm)

    result = runner.run_cold_warm_pair("openai", "gpt-test")
    assert result["verdict"] == "cache_hit_confirmed"
    assert result["contaminated"] is False
    assert result["hit_ratio"] == pytest.approx(0.98)
    assert len(result["requests"]) == 2
    assert result["requests"][0]["label"] == "cold"
    assert result["requests"][1]["label"] == "warm"
    assert result["requests"][1]["cached_tokens"] == 4900


def test_verdict_cache_miss(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    _set_parser(monkeypatch, "openai", cold, warm)

    result = runner.run_cold_warm_pair("openai", "gpt-test")
    assert result["verdict"] == "cache_miss"
    assert result["contaminated"] is False
    assert "hit_ratio" not in result  # null/absent for non-hit
    assert "Cache reuse not observed" in result["notes"]


def test_verdict_contaminated(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 100, "output_tokens": 5}
    warm = {"input_tokens": 5000, "cached_tokens": 4900, "output_tokens": 5}
    _set_parser(monkeypatch, "openai", cold, warm)

    result = runner.run_cold_warm_pair("openai", "gpt-test")
    assert result["verdict"] == "contaminated"
    assert result["contaminated"] is True
    assert "excluded" in result["notes"]


def test_verdict_error_on_parse_failure(stub_env, monkeypatch):
    def boom(*a, **kw):
        raise ValueError("simulated parser failure")
    monkeypatch.setitem(runner.VENDOR_PARSER, "openai", boom)

    result = runner.run_cold_warm_pair("openai", "gpt-test")
    assert result["verdict"] == "error"
    assert "ValueError" in result["error"]
    assert "simulated parser failure" in result["error"]


def test_verdict_error_on_driver_failure(monkeypatch):
    """If the driver context manager itself raises, capture as error verdict."""
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

    result = runner.run_cold_warm_pair("openai", "gpt-test")
    assert result["verdict"] == "error"
    assert "RuntimeError" in result["error"]
    assert "tmux launch failed" in result["error"]


def test_unknown_vendor_raises(stub_env):
    """Unknown vendor is the only failure mode that raises (programming error)."""
    with pytest.raises(ValueError, match="Unknown vendor"):
        runner.run_cold_warm_pair("not-a-vendor", "x")


def test_anthropic_field_mapping(stub_env, monkeypatch):
    """Anthropic uses cache_read_input_tokens — must map to canonical cached_tokens."""
    cold = {
        "input_tokens": 5000,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5000,
        "cache_read_input_tokens": 4800,
        "cache_creation_input_tokens": 0,
        "output_tokens": 5,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm)

    result = runner.run_cold_warm_pair("anthropic", "claude-test")
    assert result["verdict"] == "cache_hit_confirmed"
    assert result["requests"][1]["cached_tokens"] == 4800
    # cache_creation_input_tokens flows through the schema
    assert result["requests"][1]["cache_creation_input_tokens"] == 0


def test_result_passes_schema_validation(stub_env, monkeypatch):
    """Sanity: the produced result is §6.1-conformant (build_result validates,
    so this confirms the verdict-emit path doesn't bypass validation)."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5000, "cached_tokens": 4900, "output_tokens": 5}
    _set_parser(monkeypatch, "google", cold, warm)

    result = runner.run_cold_warm_pair("google", "gemini-test")
    # If we got here, validate_result inside build_result accepted it.
    assert result["vendor"] == "google"
    assert result["test_type"] == "cold_warm_pair"
    assert isinstance(result["nonce"], str)
