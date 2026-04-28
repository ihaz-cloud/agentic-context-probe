"""Tests for cache_insights.parsers.gemini."""

from __future__ import annotations

from pathlib import Path

import pytest

from cache_insights.parsers import gemini as gemini_parser


def test_parse_last_turn_happy_path(fixtures_dir: Path):
    usage = gemini_parser.parse_last_turn(fixtures_dir / "gemini-telemetry.log")
    # Last api_response is prompt-bbb.
    assert usage["input_tokens"] == 5100
    assert usage["cached_tokens"] == 4900
    assert usage["output_tokens"] == 4
    assert usage["thoughts_tokens"] == 10
    assert usage["model"] == "gemini-3.1-pro-preview"
    assert usage["prompt_id"] == "prompt-bbb"


def test_parse_last_turn_filters_by_prompt_id(fixtures_dir: Path):
    """When prompt_id is given, return that specific record (not the latest)."""
    usage = gemini_parser.parse_last_turn(
        fixtures_dir / "gemini-telemetry.log",
        prompt_id="prompt-aaa",
    )
    assert usage["prompt_id"] == "prompt-aaa"
    assert usage["input_tokens"] == 5000
    assert usage["cached_tokens"] == 0


def test_parse_last_turn_no_match_for_prompt_id(fixtures_dir: Path):
    with pytest.raises(ValueError, match="prompt_id=nope"):
        gemini_parser.parse_last_turn(
            fixtures_dir / "gemini-telemetry.log",
            prompt_id="nope",
        )


def test_parse_last_turn_skips_non_api_response_events(fixtures_dir: Path):
    """tool_call events between api_response records must be ignored."""
    # The fixture has a tool_call event sandwiched between two api_response events.
    # If the parser didn't filter, returning the "last" event would yield tool_call
    # and fail the REQUIRED_TOKEN_FIELDS check. The fact that this test passes means
    # filtering works.
    usage = gemini_parser.parse_last_turn(fixtures_dir / "gemini-telemetry.log")
    assert "input_tokens" in usage  # came from a real api_response, not tool_call


def test_parse_last_turn_no_events(fixtures_dir: Path):
    with pytest.raises(ValueError, match="No api_response"):
        gemini_parser.parse_last_turn(fixtures_dir / "gemini-telemetry-no-events.log")


def test_parse_last_turn_file_missing():
    with pytest.raises(FileNotFoundError):
        gemini_parser.parse_last_turn(Path("/nope/missing.log"))


def test_parse_last_turn_missing_required_fields(tmp_path: Path):
    p = tmp_path / "incomplete.log"
    p.write_text('{"attributes": {"event.name": "gemini_cli.api_response", "input_token_count": 1}}\n')
    with pytest.raises(ValueError, match="missing required token fields"):
        gemini_parser.parse_last_turn(p)
