"""Tests for cache_insights.parsers.claude."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cache_insights.parsers import claude as claude_parser


def test_parse_last_turn_happy_path(fixtures_dir: Path):
    usage = claude_parser.parse_last_turn(jsonl_path=fixtures_dir / "claude-session.jsonl")
    assert usage["input_tokens"] == 3
    assert usage["output_tokens"] == 12
    assert usage["cache_creation_input_tokens"] == 100
    assert usage["cache_read_input_tokens"] == 250
    assert usage["service_tier"] == "standard"
    assert usage["cache_creation"] == {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 0}
    assert usage["_source_file"].endswith("claude-session.jsonl")


def test_parse_last_turn_explicit_path_missing():
    with pytest.raises(FileNotFoundError):
        claude_parser.parse_last_turn(jsonl_path=Path("/nope/does-not-exist.jsonl"))


def test_parse_last_turn_no_assistant_usage(fixtures_dir: Path):
    with pytest.raises(ValueError, match="No assistant turn"):
        claude_parser.parse_last_turn(jsonl_path=fixtures_dir / "claude-session-no-usage.jsonl")


def test_parse_last_turn_missing_required_fields(tmp_path: Path):
    incomplete = tmp_path / "incomplete.jsonl"
    incomplete.write_text(json.dumps({
        "type": "assistant",
        "message": {"usage": {"input_tokens": 1, "output_tokens": 1}},
    }) + "\n")
    with pytest.raises(ValueError, match="missing required fields"):
        claude_parser.parse_last_turn(jsonl_path=incomplete)


def test_parse_last_turn_skips_decode_errors(tmp_path: Path):
    """Malformed JSONL lines are skipped silently."""
    p = tmp_path / "mixed.jsonl"
    p.write_text(
        "not json at all\n"
        + json.dumps({
            "type": "assistant",
            "message": {"usage": {
                "input_tokens": 7, "output_tokens": 8,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            }},
        }) + "\n"
    )
    usage = claude_parser.parse_last_turn(jsonl_path=p)
    assert usage["input_tokens"] == 7
    assert usage["output_tokens"] == 8


def test_resolve_jsonl_path_session_uuid(tmp_path: Path, monkeypatch):
    """session_uuid lookup walks CLAUDE_PROJECTS_DIR."""
    fake_root = tmp_path / "claude_projects"
    fake_root.mkdir()
    project = fake_root / "myproj"
    project.mkdir()
    target = project / "abc-123.jsonl"
    target.write_text(json.dumps({
        "type": "assistant",
        "message": {"usage": {
            "input_tokens": 1, "output_tokens": 1,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        }},
    }) + "\n")
    monkeypatch.setattr(claude_parser, "CLAUDE_PROJECTS_DIR", fake_root)
    usage = claude_parser.parse_last_turn(session_uuid="abc-123")
    assert usage["_source_file"] == str(target)


def test_resolve_jsonl_path_session_uuid_missing(tmp_path: Path, monkeypatch):
    fake_root = tmp_path / "claude_projects"
    fake_root.mkdir()
    monkeypatch.setattr(claude_parser, "CLAUDE_PROJECTS_DIR", fake_root)
    with pytest.raises(FileNotFoundError, match="session_uuid"):
        claude_parser.parse_last_turn(session_uuid="not-found")
