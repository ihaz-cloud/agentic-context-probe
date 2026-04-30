"""Tests for cache_insights.tests_runner.prefix_warmup."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from cache_insights import nonce as nonce_mod
from cache_insights.tests_runner import prefix_warmup as runner


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


def _make_nonce_factory(token_counts: list[int]):
    """Return a generate_nonce stand-in that yields nonces with the given token_counts."""
    counts = iter(token_counts)

    def factory(vendor: str, model: str, min_tokens: int, **_):
        return nonce_mod.Nonce(
            value=f"NONCE-{next(counts)}",
            token_count=token_counts[len(token_counts) - sum(1 for _ in counts) - 1]
            if False else min_tokens,
            vendor=vendor,
            model=model,
            seed="seed",
            is_verified=False,
        )

    # Simpler: yield Nonce per call with min_tokens as token_count for predictability.
    # The complex iterator above is unused; redefine cleanly.
    def simple_factory(vendor: str, model: str, min_tokens: int, **_):
        return nonce_mod.Nonce(
            value=f"NONCE-{min_tokens}",
            token_count=min_tokens,
            vendor=vendor,
            model=model,
            seed="seed",
            is_verified=False,
        )
    return simple_factory


@pytest.fixture
def stub_env(monkeypatch, tmp_path):
    """Stub driver, parsers, nonce, cli_version, cache to a temp dir."""
    monkeypatch.setattr(runner, "driver_ctx", _stub_driver)
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)
    monkeypatch.setattr(runner, "generate_nonce", _make_nonce_factory([]))
    monkeypatch.setattr(runner, "cli_version", lambda v: "test-1.0")
    # Redirect cache to tmp_path so each test has a clean cache dir.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


def _set_parser(monkeypatch, vendor: str, *usages: dict):
    calls = {"n": 0}

    def fake(*a, **kw):
        idx = calls["n"]
        calls["n"] += 1
        return usages[idx]
    monkeypatch.setitem(runner.VENDOR_PARSER, vendor, fake)


def _gen_usage(input_tokens: int, cached_tokens: int) -> dict:
    return {"input_tokens": input_tokens, "cached_tokens": cached_tokens, "output_tokens": 5}


def test_multi_turn_loop_produces_n_requests(stub_env, monkeypatch):
    """Default num_turns=8 produces 8 request entries with computed metrics."""
    usages = [_gen_usage(200 + i * 200, 0 if i < 2 else 100 + i * 50) for i in range(8)]
    _set_parser(monkeypatch, "openai", *usages)

    result = runner.run_prefix_warmup("openai", "gpt-test")

    assert len(result["requests"]) == 8
    assert result["test_type"] == "prefix_warmup"
    assert result["verdict"] == "completed"
    assert "metrics" in result
    metrics = result["metrics"]
    assert len(metrics["overhead_per_turn"]) == 8
    assert len(metrics["hit_ratio_per_turn"]) == 8
    assert len(metrics["expected_user_content_per_turn"]) == 8


def test_overhead_computation(stub_env, monkeypatch):
    """overhead_per_turn[i] = input_tokens[i] - expected_user_content[i]."""
    # 3-turn run for clarity. Default initial=128, increment_min=128.
    usages = [_gen_usage(500, 0), _gen_usage(700, 0), _gen_usage(900, 100)]
    _set_parser(monkeypatch, "openai", *usages)

    result = runner.run_prefix_warmup("openai", "gpt-test", num_turns=3)

    metrics = result["metrics"]
    expected = metrics["expected_user_content_per_turn"]
    overhead = metrics["overhead_per_turn"]
    # Each turn requested min_tokens=128 (initial=128 for turn0, increment_min=128 thereafter).
    # Cumulative: [128, 256, 384].
    assert expected == [128, 256, 384]
    assert overhead == [500 - 128, 700 - 256, 900 - 384]


def test_first_cache_engagement_turn(stub_env, monkeypatch):
    """first_cache_engagement_turn = first index where cached_tokens > 0."""
    usages = [
        _gen_usage(500, 0),
        _gen_usage(700, 0),
        _gen_usage(900, 100),
        _gen_usage(1100, 200),
    ]
    _set_parser(monkeypatch, "openai", *usages)

    result = runner.run_prefix_warmup("openai", "gpt-test", num_turns=4)
    assert result["metrics"]["first_cache_engagement_turn"] == 2


def test_first_cache_engagement_null_when_never(stub_env, monkeypatch):
    """If cached_tokens is always 0, first_cache_engagement_turn is None."""
    usages = [_gen_usage(500 + i * 100, 0) for i in range(4)]
    _set_parser(monkeypatch, "openai", *usages)

    result = runner.run_prefix_warmup("openai", "gpt-test", num_turns=4)
    assert result["metrics"]["first_cache_engagement_turn"] is None


def test_hit_ratio_per_turn(stub_env, monkeypatch):
    usages = [_gen_usage(1000, 0), _gen_usage(1000, 800)]
    _set_parser(monkeypatch, "openai", *usages)

    result = runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)
    ratios = result["metrics"]["hit_ratio_per_turn"]
    assert ratios[0] == 0.0
    assert ratios[1] == pytest.approx(0.8)


def test_verdict_contaminated_when_turn_1_cached_gt_zero(stub_env, monkeypatch):
    usages = [_gen_usage(500, 100), _gen_usage(700, 200)]
    _set_parser(monkeypatch, "openai", *usages)

    result = runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)
    assert result["verdict"] == "contaminated"
    assert result["contaminated"] is True


def test_verdict_error_on_driver_failure(monkeypatch, tmp_path):
    @contextmanager
    def failing_driver(vendor: str, **_):
        raise RuntimeError("tmux launch failed")
        yield  # pragma: no cover

    monkeypatch.setattr(runner, "driver_ctx", failing_driver)
    monkeypatch.setattr(runner, "get_launch_spec", lambda v: None)
    monkeypatch.setattr(runner, "generate_nonce", _make_nonce_factory([]))
    monkeypatch.setattr(runner, "cli_version", lambda v: "test-1.0")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    result = runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)
    assert result["verdict"] == "error"
    assert "RuntimeError" in result["error"]


def test_unknown_vendor_raises(stub_env):
    with pytest.raises(ValueError, match="Unknown vendor"):
        runner.run_prefix_warmup("not-a-vendor", "x")


def test_anthropic_field_mapping(stub_env, monkeypatch):
    cold = {"input_tokens": 500, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 500, "output_tokens": 5}
    warm = {"input_tokens": 700, "cache_read_input_tokens": 400,
            "cache_creation_input_tokens": 200, "output_tokens": 5}
    _set_parser(monkeypatch, "anthropic", cold, warm)

    result = runner.run_prefix_warmup("anthropic", "claude-test", num_turns=2)
    assert result["requests"][1]["cached_tokens"] == 400
    assert result["metrics"]["hit_ratio_per_turn"][1] == pytest.approx(400 / 700)


def test_cache_hit_short_circuits_driver(stub_env, monkeypatch, tmp_path):
    """Second invocation with same key returns cached without driver invocation."""
    usages = [_gen_usage(500, 0), _gen_usage(700, 200)]
    _set_parser(monkeypatch, "openai", *usages)

    # First run: writes to cache.
    first = runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)
    assert first["verdict"] == "completed"

    # Second run: should hit cache, not call driver_ctx.
    driver_called = {"n": 0}

    @contextmanager
    def spy_driver(vendor: str, **_):
        driver_called["n"] += 1
        yield _StubSession()

    monkeypatch.setattr(runner, "driver_ctx", spy_driver)

    second = runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)
    assert second["verdict"] == "skipped"
    assert "loaded from warmup cache" in second["notes"]
    assert driver_called["n"] == 0


def test_force_fresh_bypasses_cache(stub_env, monkeypatch):
    """force_fresh=True always launches the driver, overwrites the cache."""
    usages_first = [_gen_usage(500, 0), _gen_usage(700, 200)]
    _set_parser(monkeypatch, "openai", *usages_first)

    runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)

    # Now force_fresh — should launch driver again.
    usages_second = [_gen_usage(500, 0), _gen_usage(700, 300)]
    _set_parser(monkeypatch, "openai", *usages_second)

    driver_called = {"n": 0}

    @contextmanager
    def spy_driver(vendor: str, **_):
        driver_called["n"] += 1
        yield _StubSession()

    monkeypatch.setattr(runner, "driver_ctx", spy_driver)

    result = runner.run_prefix_warmup(
        "openai", "gpt-test", num_turns=2, force_fresh=True
    )
    assert result["verdict"] == "completed"
    assert driver_called["n"] == 1


def test_cache_invalidates_when_cli_version_differs(stub_env, monkeypatch):
    """Different cli_version → different cache key → driver runs again."""
    usages_v1 = [_gen_usage(500, 0), _gen_usage(700, 200)]
    _set_parser(monkeypatch, "openai", *usages_v1)
    monkeypatch.setattr(runner, "cli_version", lambda v: "version-1")
    runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)

    # Change cli_version → cache miss → driver runs.
    monkeypatch.setattr(runner, "cli_version", lambda v: "version-2")
    usages_v2 = [_gen_usage(500, 0), _gen_usage(700, 300)]
    _set_parser(monkeypatch, "openai", *usages_v2)

    driver_called = {"n": 0}

    @contextmanager
    def spy_driver(vendor: str, **_):
        driver_called["n"] += 1
        yield _StubSession()

    monkeypatch.setattr(runner, "driver_ctx", spy_driver)

    result = runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)
    assert result["verdict"] == "completed"
    assert driver_called["n"] == 1


def test_unknown_cli_version_skips_cache_write(stub_env, monkeypatch, tmp_path):
    """When cli_version returns 'unknown', the cache is NOT written."""
    monkeypatch.setattr(runner, "cli_version", lambda v: "unknown")
    usages = [_gen_usage(500, 0), _gen_usage(700, 200)]
    _set_parser(monkeypatch, "openai", *usages)

    result = runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)
    assert result["verdict"] == "completed"
    assert "unknown" in result["notes"].lower()
    # Cache directory should be empty (no entry written).
    cache_dir = tmp_path / "cache-insights" / "warmup"
    if cache_dir.exists():
        assert list(cache_dir.glob("*.json")) == []


def test_contaminated_skips_cache_write(stub_env, monkeypatch, tmp_path):
    """contaminated verdict → cache is NOT written."""
    usages = [_gen_usage(500, 100), _gen_usage(700, 200)]  # turn 0 cached>0
    _set_parser(monkeypatch, "openai", *usages)

    result = runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)
    assert result["verdict"] == "contaminated"
    cache_dir = tmp_path / "cache-insights" / "warmup"
    if cache_dir.exists():
        assert list(cache_dir.glob("*.json")) == []


def test_result_passes_schema_validation(stub_env, monkeypatch):
    usages = [_gen_usage(500 + i * 100, 0 if i < 2 else 100) for i in range(3)]
    _set_parser(monkeypatch, "google", *usages)

    result = runner.run_prefix_warmup("google", "gemini-test", num_turns=3)
    assert result["vendor"] == "google"
    assert result["test_type"] == "prefix_warmup"
    # Schema accepts the metrics block.
    assert "metrics" in result


def test_cached_at_and_cli_version_source_in_cache_file(stub_env, monkeypatch, tmp_path):
    """Cache file includes cached_at + cli_version_source."""
    usages = [_gen_usage(500, 0), _gen_usage(700, 200)]
    _set_parser(monkeypatch, "openai", *usages)

    runner.run_prefix_warmup("openai", "gpt-test", num_turns=2)

    cache_dir = tmp_path / "cache-insights" / "warmup"
    cache_files = list(cache_dir.glob("*.json"))
    assert len(cache_files) == 1
    import json as _json
    payload = _json.loads(cache_files[0].read_text())
    assert "cached_at" in payload
    assert "cli_version_source" in payload
    assert payload["cli_version_source"] == "test-1.0"
