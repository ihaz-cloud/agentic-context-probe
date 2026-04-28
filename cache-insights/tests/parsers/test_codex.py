"""Tests for cache_insights.parsers.codex."""

from __future__ import annotations

from pathlib import Path

import pytest

from cache_insights.parsers import codex as codex_parser


def test_parse_last_turn_happy_path(fixtures_dir: Path):
    usage = codex_parser.parse_last_turn(fixtures_dir / "codex-otlp.jsonl")
    # The fixture has two records; parse_last_turn returns the LAST.
    assert usage["input_tokens"] == 5050
    assert usage["cached_tokens"] == 4900
    assert usage["output_tokens"] == 10
    assert usage["model"] == "gpt-5.3-codex"
    assert usage["_source_file"].endswith("codex-otlp.jsonl")


def test_int_coercion_handles_string_and_int_envelopes(fixtures_dir: Path):
    """First record uses stringValue for input/output, intValue for cached_token_count.

    Both must coerce to int."""
    # Use only the first record by truncating the fixture into a tmp file.
    src = (fixtures_dir / "codex-otlp.jsonl").read_text().splitlines()[0]
    p = fixtures_dir.parent / "_tmp_codex_first_line.jsonl"
    p.write_text(src + "\n")
    try:
        usage = codex_parser.parse_last_turn(p)
        assert isinstance(usage["input_tokens"], int) and usage["input_tokens"] == 5000
        assert isinstance(usage["cached_tokens"], int) and usage["cached_tokens"] == 0
        assert isinstance(usage["output_tokens"], int) and usage["output_tokens"] == 12
        assert usage["reasoning_tokens"] == 8
        assert usage["tool_tokens"] == 0
    finally:
        p.unlink()


def test_parse_last_turn_filters_other_services(fixtures_dir: Path):
    with pytest.raises(ValueError, match="No Codex usage records"):
        codex_parser.parse_last_turn(fixtures_dir / "codex-otlp-other-service.jsonl")


def test_parse_last_turn_file_missing():
    with pytest.raises(FileNotFoundError):
        codex_parser.parse_last_turn(Path("/nope/does-not-exist.jsonl"))


def test_otlp_attrs_to_dict_unwraps_envelope():
    attrs = [
        {"key": "s", "value": {"stringValue": "hi"}},
        {"key": "i", "value": {"intValue": "42"}},
        {"key": "d", "value": {"doubleValue": 1.5}},
        {"key": "b", "value": {"boolValue": True}},
        {"key": "noval", "value": {}},
    ]
    out = codex_parser._otlp_attrs_to_dict(attrs)
    assert out["s"] == "hi"
    assert out["i"] == 42
    assert out["d"] == 1.5
    assert out["b"] is True
    assert out["noval"] == {}


def test_otlp_attrs_to_dict_handles_missing_key():
    out = codex_parser._otlp_attrs_to_dict([{"value": {"stringValue": "x"}}])
    assert out == {}
