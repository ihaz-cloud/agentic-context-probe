"""Tests for cache_insights.nonce.generate_nonce."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cache_insights import nonce as nonce_mod


def test_generate_nonce_unverified_meets_floor(tmp_path: Path):
    """With verify=False the heuristic estimate is used; value must clear the floor."""
    cache = tmp_path / "cache.json"
    n = nonce_mod.generate_nonce(
        vendor="openai",
        model="gpt-test",
        min_tokens=256,
        seed="seed-A",
        cache_path=cache,
        verify=False,
    )
    assert n.is_verified is False
    assert n.token_count >= 256
    assert n.vendor == "openai"
    assert n.model == "gpt-test"
    assert n.seed == "seed-A"
    assert n.value.endswith("\n")
    assert n.content_hash  # auto-populated in __post_init__


def test_generate_nonce_deterministic_from_seed(tmp_path: Path):
    n1 = nonce_mod.generate_nonce(
        vendor="anthropic", model="claude", min_tokens=64,
        seed="same-seed", cache_path=tmp_path / "c1.json", verify=False,
    )
    n2 = nonce_mod.generate_nonce(
        vendor="anthropic", model="claude", min_tokens=64,
        seed="same-seed", cache_path=tmp_path / "c2.json", verify=False,
    )
    assert n1.value == n2.value
    assert n1.content_hash == n2.content_hash


def test_generate_nonce_unknown_vendor_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown vendor"):
        nonce_mod.generate_nonce(
            vendor="unknown-vendor", model="x", min_tokens=64,
            cache_path=tmp_path / "c.json", verify=False,
        )


def test_generate_nonce_uses_cache_hit(tmp_path: Path, monkeypatch):
    """When the (content, vendor, model) hash is already cached, re-use the count
    without calling the vendor API."""
    cache_path = tmp_path / "cache.json"

    # Phase 1: pre-compute what the nonce VALUE will be, then prime the cache
    # with a known token_count for that exact value/vendor/model.
    seed = "primed-seed"
    n_warmup = nonce_mod.generate_nonce(
        vendor="google", model="gemini-test", min_tokens=64,
        seed=seed, cache_path=cache_path, verify=False,
    )
    chash = nonce_mod._content_hash(n_warmup.value, "google", "gemini-test")
    cache_path.write_text(json.dumps({
        chash: {
            "vendor": "google",
            "model": "gemini-test",
            "token_count": 999,
            "verified": True,
        }
    }))

    # Phase 2: stub COUNT_TOKENS_BY_VENDOR["google"] to fail loudly if called,
    # confirming the cached entry is honored.
    def boom(*a, **kw):
        raise AssertionError("vendor API should not be called on cache hit")
    monkeypatch.setitem(nonce_mod.COUNT_TOKENS_BY_VENDOR, "google", boom)

    n = nonce_mod.generate_nonce(
        vendor="google", model="gemini-test", min_tokens=64,
        seed=seed, cache_path=cache_path, verify=True,
    )
    assert n.is_verified is True
    assert n.token_count == 999


def test_generate_nonce_verify_falls_back_when_api_key_missing(tmp_path: Path, monkeypatch):
    """If the vendor count_tokens raises RuntimeError (no key), the heuristic
    estimate is returned with is_verified=False — no exception bubbles up."""
    cache_path = tmp_path / "cache.json"

    def no_key(*a, **kw):
        raise RuntimeError("API key missing")
    monkeypatch.setitem(nonce_mod.COUNT_TOKENS_BY_VENDOR, "openai", no_key)

    n = nonce_mod.generate_nonce(
        vendor="openai", model="gpt-test", min_tokens=64,
        seed="any", cache_path=cache_path, verify=True,
    )
    assert n.is_verified is False
    assert n.token_count >= 64
    assert not cache_path.exists()  # nothing cached on RuntimeError
