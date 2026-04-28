"""Gemini OTel telemetry parser — read per-turn cache attribution from telemetry.log."""

from __future__ import annotations

from pathlib import Path

from cache_insights.parsers._io import iter_pretty_json_records

GEMINI_TELEMETRY_LOG = Path.home() / ".gemini" / "telemetry.log"

API_RESPONSE_EVENT = "gemini_cli.api_response"

REQUIRED_TOKEN_FIELDS = (
    "input_token_count",
    "output_token_count",
    "cached_content_token_count",
)


def _is_api_response(record: dict) -> bool:
    attrs = record.get("attributes")
    return isinstance(attrs, dict) and attrs.get("event.name") == API_RESPONSE_EVENT


def parse_last_turn(
    log_path: Path | None = None,
    prompt_id: str | None = None,
) -> dict:
    """Return the last (or specified) Gemini api_response record's token usage.

    Args:
        log_path: explicit path to a telemetry log file. Defaults to
            ~/.gemini/telemetry.log.
        prompt_id: when supplied, return the most recent api_response record
            whose attributes['prompt_id'] matches. Otherwise return the
            most recent api_response record overall.

    Returns:
        Dict with input_tokens, output_tokens, cached_tokens, thoughts_tokens,
        tool_tokens, total_tokens, prompt_id, model, _source_file.

    Raises:
        FileNotFoundError if the log file does not exist.
        ValueError if no api_response record (or no matching prompt_id) is found.
    """
    path = Path(log_path) if log_path is not None else GEMINI_TELEMETRY_LOG
    if not path.exists():
        raise FileNotFoundError(f"Gemini telemetry log not found at {path}")

    last_match: dict | None = None
    for record in iter_pretty_json_records(path):
        if not _is_api_response(record):
            continue
        attrs = record["attributes"]
        if prompt_id is not None and attrs.get("prompt_id") != prompt_id:
            continue
        last_match = attrs

    if last_match is None:
        if prompt_id is not None:
            raise ValueError(
                f"No api_response record with prompt_id={prompt_id} in {path}"
            )
        raise ValueError(f"No api_response records found in {path}")

    missing = [k for k in REQUIRED_TOKEN_FIELDS if k not in last_match]
    if missing:
        raise ValueError(
            f"api_response record in {path} missing required token fields: {missing}"
        )

    return {
        "input_tokens": last_match["input_token_count"],
        "output_tokens": last_match["output_token_count"],
        "cached_tokens": last_match["cached_content_token_count"],
        "thoughts_tokens": last_match.get("thoughts_token_count"),
        "tool_tokens": last_match.get("tool_token_count"),
        "total_tokens": last_match.get("total_token_count"),
        "prompt_id": last_match.get("prompt_id"),
        "model": last_match.get("model"),
        "_source_file": str(path),
    }
