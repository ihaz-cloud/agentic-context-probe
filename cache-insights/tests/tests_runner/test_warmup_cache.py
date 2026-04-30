"""Unit tests for cache_insights.tests_runner._warmup_cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cache_insights.tests_runner import _warmup_cache as wc


def test_cache_path_for_uses_xdg_cache_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    p = wc.cache_path_for("anthropic", "claude-opus-4-7", "1.0.123")
    assert str(p).endswith("/xdg/cache-insights/warmup/anthropic__claude-opus-4-7__1.0.123.json")


def test_cache_path_for_falls_back_to_home_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(wc.Path, "home", classmethod(lambda cls: tmp_path))
    p = wc.cache_path_for("openai", "gpt-test", "0.122.0")
    assert p == tmp_path / ".cache" / "cache-insights" / "warmup" / "openai__gpt-test__0.122.0.json"


def test_cache_path_for_sanitizes_unsafe_chars(monkeypatch, tmp_path):
    monkeypatch.setattr(wc.Path, "home", classmethod(lambda cls: tmp_path))
    p = wc.cache_path_for("vendor/x", "model with space", "v 1.0")
    # Forward slashes, spaces — replaced with underscores.
    assert "/" not in p.name.split(".")[0]
    assert " " not in p.name


def test_load_cached_returns_none_for_missing_file(tmp_path):
    assert wc.load_cached(tmp_path / "nonexistent.json") is None


def test_load_cached_returns_none_for_malformed_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not valid json {")
    assert wc.load_cached(p) is None


def test_load_cached_returns_none_for_non_object_top_level(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]")
    assert wc.load_cached(p) is None


def test_load_cached_returns_dict_for_valid_file(tmp_path):
    p = tmp_path / "good.json"
    p.write_text(json.dumps({"verdict": "completed", "vendor": "openai"}))
    loaded = wc.load_cached(p)
    assert loaded == {"verdict": "completed", "vendor": "openai"}


def test_write_cached_creates_parent_dir(tmp_path):
    p = tmp_path / "deep" / "nest" / "out.json"
    wc.write_cached(p, {"x": 1})
    assert p.exists()
    assert json.loads(p.read_text()) == {"x": 1}


def test_write_cached_atomic_replace(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"prior": True}))
    wc.write_cached(p, {"new": True})
    assert json.loads(p.read_text()) == {"new": True}


def test_write_cached_preserves_prior_on_serialization_failure(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"prior": True}))

    class _Unserializable:
        pass

    with pytest.raises(TypeError):
        wc.write_cached(p, {"x": _Unserializable()})

    # Prior file is intact.
    assert json.loads(p.read_text()) == {"prior": True}
    # No leftover .tmp files in the dir.
    leftover = list(p.parent.glob("*.tmp"))
    assert leftover == []


def test_write_then_load_roundtrip(tmp_path):
    p = tmp_path / "rt.json"
    payload = {"verdict": "completed", "metrics": {"hit_ratio_per_turn": [0.0, 0.5, 0.9]}}
    wc.write_cached(p, payload)
    assert wc.load_cached(p) == payload
