"""Tests for cache_insights.tokenizers."""

from __future__ import annotations

import pytest

from cache_insights import tokenizers


def test_estimate_tokens_empty():
    assert tokenizers.estimate_tokens("") == 0


def test_estimate_tokens_returns_int():
    n = tokenizers.estimate_tokens("hello world")
    assert isinstance(n, int)
    assert n > 0


def test_estimate_tokens_scales_with_length():
    short = tokenizers.estimate_tokens("a" * 100)
    long = tokenizers.estimate_tokens("a" * 10_000)
    assert long > short


def test_count_tokens_unknown_vendor_raises():
    with pytest.raises(ValueError, match="Unknown vendor"):
        tokenizers.count_tokens("hi", vendor="not-real", model="x")


def test_count_tokens_dispatches_to_vendor(monkeypatch):
    """count_tokens routes to the registered vendor function."""
    called = {}

    def fake(text, model):
        called["text"] = text
        called["model"] = model
        return 7
    monkeypatch.setitem(tokenizers.COUNT_TOKENS_BY_VENDOR, "openai", fake)

    assert tokenizers.count_tokens("hello", vendor="openai", model="gpt-test") == 7
    assert called == {"text": "hello", "model": "gpt-test"}


def test_count_tokens_openai_missing_key_raises_runtime(monkeypatch):
    """When OPENAI_API_KEY is empty, count_tokens_openai raises RuntimeError."""
    # load_env_var is lru_cached, so we patch the underlying function the
    # tokenizer module imported at module load time.
    monkeypatch.setattr(tokenizers, "load_env_var", lambda name: "")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        tokenizers.count_tokens_openai("hello", model="gpt-test")


def test_count_tokens_anthropic_missing_key_raises_runtime(monkeypatch):
    monkeypatch.setattr(tokenizers, "load_env_var", lambda name: "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        tokenizers.count_tokens_anthropic("hello", model="claude-test")


def test_count_tokens_google_missing_key_raises_runtime(monkeypatch):
    monkeypatch.setattr(tokenizers, "load_env_var", lambda name: "")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        tokenizers.count_tokens_google("hello", model="gemini-test")


def test_count_tokens_by_vendor_registry_complete():
    """All three documented vendors must be registered."""
    assert set(tokenizers.COUNT_TOKENS_BY_VENDOR.keys()) == {"openai", "anthropic", "google"}
