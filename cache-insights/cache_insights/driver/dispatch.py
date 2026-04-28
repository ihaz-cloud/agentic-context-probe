"""Per-vendor launch + completion specs for the tmux driver.

Each LaunchSpec defines how to start a vendor's interactive CLI, how to format
the prompt-completion sentinel, and what file to watch for completion. Adding
a vendor is a single dict entry — no new module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class LaunchSpec:
    """Launch + completion contract for one vendor.

    Attributes:
        vendor: vendor slug (openai/anthropic/google).
        binary: CLI executable name (looked up via PATH).
        default_args: standard argv tail for an interactive launch.
        completion_source: factory that returns the file path the completion
            poller should watch. Receives a `session_uuid` keyword for vendors
            that emit per-session files (Claude); ignores it otherwise.
        completion_check: predicate taking the watched file path and returning
            True when the post-prompt usage record has appeared. Should be
            idempotent and safe to call repeatedly during polling.
        compact_command: in-CLI slash command (or empty) to invoke compaction.
        rewind_keys: tmux send-keys argument list to invoke rewind, or None.
    """

    vendor: str
    binary: str
    default_args: tuple[str, ...]
    completion_source: Callable[..., Path]
    completion_check: Callable[[Path], bool]
    compact_command: str
    rewind_keys: tuple[str, ...] | None


def _claude_completion_source(session_uuid: str | None = None, **_: object) -> Path:
    """Path to the latest Claude session JSONL.

    If session_uuid is supplied, return the matching file. Otherwise return
    the most-recently-modified JSONL under ~/.claude/projects/.
    """
    base = Path.home() / ".claude" / "projects"
    if session_uuid:
        matches = list(base.rglob(f"{session_uuid}.jsonl"))
        if matches:
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return matches[0]
    jsonls = sorted(base.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return jsonls[-1] if jsonls else base / "missing.jsonl"


def _claude_completion_check(path: Path) -> bool:
    from cache_insights.parsers.claude import parse_last_turn

    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        parse_last_turn(jsonl_path=path)
        return True
    except (FileNotFoundError, ValueError):
        return False


def _gemini_completion_source(**_: object) -> Path:
    return Path.home() / ".gemini" / "telemetry.log"


def _gemini_completion_check(path: Path) -> bool:
    from cache_insights.parsers.gemini import parse_last_turn

    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        parse_last_turn(log_path=path)
        return True
    except (FileNotFoundError, ValueError):
        return False


def _codex_completion_source(**_: object) -> Path:
    return Path("/tmp/otel-data/codex-logs.jsonl")


def _codex_completion_check(path: Path) -> bool:
    from cache_insights.parsers.codex import parse_last_turn

    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        parse_last_turn(log_path=path)
        return True
    except (FileNotFoundError, ValueError):
        return False


VENDOR_LAUNCH: dict[str, LaunchSpec] = {
    "anthropic": LaunchSpec(
        vendor="anthropic",
        binary="claude",
        default_args=(),
        completion_source=_claude_completion_source,
        completion_check=_claude_completion_check,
        compact_command="/compact",
        rewind_keys=("Escape", "Escape"),
    ),
    "google": LaunchSpec(
        vendor="google",
        binary="gemini",
        default_args=(),
        completion_source=_gemini_completion_source,
        completion_check=_gemini_completion_check,
        compact_command="/compress",
        rewind_keys=None,
    ),
    "openai": LaunchSpec(
        vendor="openai",
        binary="codex",
        default_args=(),
        completion_source=_codex_completion_source,
        completion_check=_codex_completion_check,
        compact_command="/compact",
        rewind_keys=None,
    ),
}


def get_launch_spec(vendor: str) -> LaunchSpec:
    if vendor not in VENDOR_LAUNCH:
        raise ValueError(
            f"Unknown vendor {vendor!r}; expected one of {sorted(VENDOR_LAUNCH)}"
        )
    return VENDOR_LAUNCH[vendor]
