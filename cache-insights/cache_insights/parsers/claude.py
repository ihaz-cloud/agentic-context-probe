"""Claude JSONL parser — read per-turn cache attribution from session files."""

from __future__ import annotations

import json
from pathlib import Path

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

REQUIRED_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _resolve_jsonl_path(jsonl_path: Path | None, session_uuid: str | None) -> Path:
    if jsonl_path is not None:
        path = Path(jsonl_path)
        if not path.exists():
            raise FileNotFoundError(f"Claude JSONL not found at {path}")
        return path

    if session_uuid is not None:
        matches = list(CLAUDE_PROJECTS_DIR.rglob(f"{session_uuid}.jsonl"))
        if not matches:
            raise FileNotFoundError(
                f"No Claude JSONL found for session_uuid={session_uuid} under {CLAUDE_PROJECTS_DIR}"
            )
        if len(matches) > 1:
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return matches[0]

    if not CLAUDE_PROJECTS_DIR.exists():
        raise FileNotFoundError(f"Claude projects dir not found: {CLAUDE_PROJECTS_DIR}")
    jsonls = sorted(CLAUDE_PROJECTS_DIR.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not jsonls:
        raise FileNotFoundError(f"No Claude JSONL files under {CLAUDE_PROJECTS_DIR}")
    return jsonls[-1]


def parse_last_turn(
    jsonl_path: Path | None = None,
    session_uuid: str | None = None,
) -> dict:
    """Return the last assistant turn's usage block from a Claude session JSONL.

    Resolution order: explicit jsonl_path > session_uuid lookup > most-recent fallback.
    Raises FileNotFoundError if no JSONL can be resolved, ValueError if the resolved
    JSONL has no assistant turn with a usage block yet.
    """
    path = _resolve_jsonl_path(jsonl_path, session_uuid)

    last_usage: dict | None = None
    with path.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "assistant":
                continue
            usage = rec.get("message", {}).get("usage")
            if usage:
                last_usage = usage

    if last_usage is None:
        raise ValueError(
            f"No assistant turn with usage block found in {path}"
        )

    missing = [k for k in REQUIRED_USAGE_FIELDS if k not in last_usage]
    if missing:
        raise ValueError(
            f"Usage block in {path} missing required fields: {missing}"
        )

    result = {
        "input_tokens": last_usage["input_tokens"],
        "output_tokens": last_usage["output_tokens"],
        "cache_creation_input_tokens": last_usage["cache_creation_input_tokens"],
        "cache_read_input_tokens": last_usage["cache_read_input_tokens"],
        "cache_creation": last_usage.get("cache_creation"),
        "service_tier": last_usage.get("service_tier"),
        "_source_file": str(path),
    }
    return result
