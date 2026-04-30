"""Tests for cache_insights.tests_runner.content_growth.

Real CLIs are NOT invoked. The driver context manager is mocked to yield a
stub session; the vendor-specific parse_last_turn is patched to return
controlled usage dicts so we exercise verdict logic deterministically across
the 4-turn sequence.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from cache_insights import nonce as nonce_mod
from cache_insights.tests_runner import content_growth as runner


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


def _two_nonces(vendor: str = "openai", model: str = "gpt-test"):
    return iter([
        nonce_mod.Nonce(
            value="NONCE-A-VALUE", token_count=4096, vendor=vendor,
            model=model, seed="seed-a", is_verified=False,
        ),
        nonce_mod.Nonce(
            value="NONCE-B-VALUE", token_count=2048, vendor=vendor,
            model=model, seed="seed-b", is_verified=False,
        ),
    ])


@pytest.fixture
def stub_env(monkeypatch):
    """Stub the driver context manager and vendor parsers; deterministic nonces."""
    monkeypatch.setattr(runner, "driver_ctx", _stub_driver)
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)

    nonces = _two_nonces()
    monkeypatch.setattr(runner, "generate_nonce", lambda **_: next(nonces))


def _set_parser(monkeypatch, vendor: str, *usages: dict):
    """Install a parser that returns successive ``usages`` on each call."""
    calls = {"n": 0}

    def fake(*a, **kw):
        idx = calls["n"]
        calls["n"] += 1
        return usages[idx]
    monkeypatch.setitem(runner.VENDOR_PARSER, vendor, fake)


def test_verdict_cache_hit_confirmed(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5, "model": "gpt-x"}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3, "model": "gpt-x"}
    growth = {"input_tokens": 7100, "cached_tokens": 4900, "output_tokens": 5, "model": "gpt-x"}
    post = {"input_tokens": 7105, "cached_tokens": 7000, "output_tokens": 3, "model": "gpt-x"}
    _set_parser(monkeypatch, "openai", cold, warm, growth, post)

    result = runner.run_content_growth("openai", "gpt-test")
    assert result["verdict"] == "cache_hit_confirmed"
    assert result["contaminated"] is False
    assert result["hit_ratio"] == pytest.approx(7000 / 7105)
    assert len(result["requests"]) == 4
    labels = [r["label"] for r in result["requests"]]
    assert labels == ["cold", "warm_baseline", "growth_t2", "post_growth"]
    assert result["requests"][3]["cached_tokens"] == 7000


def test_verdict_cache_miss(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    growth = {"input_tokens": 7100, "cached_tokens": 4900, "output_tokens": 5}
    post = {"input_tokens": 7105, "cached_tokens": 0, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, growth, post)

    result = runner.run_content_growth("openai", "gpt-test")
    assert result["verdict"] == "cache_miss"
    assert result["contaminated"] is False
    assert "hit_ratio" not in result
    assert "invalidated" in result["notes"].lower()


def test_verdict_contaminated(stub_env, monkeypatch):
    cold = {"input_tokens": 5000, "cached_tokens": 100, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    growth = {"input_tokens": 7100, "cached_tokens": 4900, "output_tokens": 5}
    post = {"input_tokens": 7105, "cached_tokens": 7000, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, growth, post)

    result = runner.run_content_growth("openai", "gpt-test")
    assert result["verdict"] == "contaminated"
    assert result["contaminated"] is True
    assert "excluded" in result["notes"]


def test_verdict_error_on_parse_failure_mid_sequence(stub_env, monkeypatch):
    """If the parser fails on turn 3, partial requests (cold + warm_baseline) are retained."""
    calls = {"n": 0}

    def fake(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
        if calls["n"] == 2:
            return {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
        raise ValueError("simulated parser failure on turn 3")

    monkeypatch.setitem(runner.VENDOR_PARSER, "openai", fake)

    result = runner.run_content_growth("openai", "gpt-test")
    assert result["verdict"] == "error"
    assert "ValueError" in result["error"]
    assert "simulated parser failure" in result["error"]
    assert len(result["requests"]) == 2
    assert [r["label"] for r in result["requests"]] == ["cold", "warm_baseline"]


def test_verdict_error_on_driver_failure(monkeypatch):
    """If the driver context manager itself raises, capture as error verdict."""
    @contextmanager
    def failing_driver(vendor: str, **_):
        raise RuntimeError("tmux launch failed")
        yield  # pragma: no cover

    monkeypatch.setattr(runner, "driver_ctx", failing_driver)
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)

    nonces = _two_nonces()
    monkeypatch.setattr(runner, "generate_nonce", lambda **_: next(nonces))

    result = runner.run_content_growth("openai", "gpt-test")
    assert result["verdict"] == "error"
    assert "RuntimeError" in result["error"]
    assert "tmux launch failed" in result["error"]
    assert len(result["requests"]) == 0


def test_unknown_vendor_raises(stub_env):
    """Unknown vendor is the only failure mode that raises (programming error)."""
    with pytest.raises(ValueError, match="Unknown vendor"):
        runner.run_content_growth("not-a-vendor", "x")


def test_anthropic_field_mapping(stub_env, monkeypatch):
    """Anthropic uses cache_read_input_tokens — must map to canonical cached_tokens."""
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    growth = {
        "input_tokens": 7100, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 2050, "output_tokens": 5,
    }
    post = {
        "input_tokens": 7105, "cache_read_input_tokens": 7000,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, growth, post)

    result = runner.run_content_growth("anthropic", "claude-test")
    assert result["verdict"] == "cache_hit_confirmed"
    assert result["requests"][3]["cached_tokens"] == 7000
    assert result["requests"][2]["cache_creation_input_tokens"] == 2050


def test_anthropic_cache_miss_includes_cache_control_note(stub_env, monkeypatch):
    """Anthropic-specific note appears when post-growth cached==0."""
    cold = {
        "input_tokens": 5000, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5000, "output_tokens": 5,
    }
    warm = {
        "input_tokens": 5005, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    growth = {
        "input_tokens": 7100, "cache_read_input_tokens": 4900,
        "cache_creation_input_tokens": 2050, "output_tokens": 5,
    }
    post = {
        "input_tokens": 7105, "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0, "output_tokens": 3,
    }
    _set_parser(monkeypatch, "anthropic", cold, warm, growth, post)

    result = runner.run_content_growth("anthropic", "claude-test")
    assert result["verdict"] == "cache_miss"
    assert "cache_control" in result["notes"]


def test_two_nonce_concatenation(stub_env, monkeypatch):
    """Result `nonce` field contains both nonce A and nonce B values verbatim."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    growth = {"input_tokens": 7100, "cached_tokens": 4900, "output_tokens": 5}
    post = {"input_tokens": 7105, "cached_tokens": 7000, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, growth, post)

    result = runner.run_content_growth("openai", "gpt-test")
    nonce_field = result["nonce"]
    assert "NONCE-A-VALUE" in nonce_field
    assert "NONCE-B-VALUE" in nonce_field
    assert "---NONCE-B---" in nonce_field
    # Total payload sums across both nonces; prefix is just A.
    assert result["total_payload_tokens"] == 4096 + 2048
    assert result["nonce_prefix_tokens"] == 4096


def test_result_passes_schema_validation(stub_env, monkeypatch):
    """Sanity: the produced result is §6.1-conformant (build_result validates)."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    growth = {"input_tokens": 7100, "cached_tokens": 4900, "output_tokens": 5}
    post = {"input_tokens": 7105, "cached_tokens": 7000, "output_tokens": 3}
    _set_parser(monkeypatch, "google", cold, warm, growth, post)

    result = runner.run_content_growth("google", "gemini-test")
    assert result["vendor"] == "google"
    assert result["test_type"] == "content_growth"
    assert isinstance(result["nonce"], str)


def test_prompts_sent_in_correct_order(stub_env, monkeypatch):
    """The 4-turn sequence sends nonce A, 'say alpha', nonce B, 'say bravo'."""
    cold = {"input_tokens": 5000, "cached_tokens": 0, "output_tokens": 5}
    warm = {"input_tokens": 5005, "cached_tokens": 4900, "output_tokens": 3}
    growth = {"input_tokens": 7100, "cached_tokens": 4900, "output_tokens": 5}
    post = {"input_tokens": 7105, "cached_tokens": 7000, "output_tokens": 3}
    _set_parser(monkeypatch, "openai", cold, warm, growth, post)

    captured: list[str] = []

    class _CapturingSession(_StubSession):
        def send_prompt(self, text: str) -> None:
            captured.append(text)

    @contextmanager
    def _capturing_driver(vendor: str, **_):
        yield _CapturingSession()

    monkeypatch.setattr(runner, "driver_ctx", _capturing_driver)

    runner.run_content_growth("openai", "gpt-test")
    assert captured == ["NONCE-A-VALUE", "say alpha", "NONCE-B-VALUE", "say bravo"]
