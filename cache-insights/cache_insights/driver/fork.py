"""Vendor-agnostic fork helper.

§4.1 suffix-variation (cache-insights-0to.4) and §4.2 fork primitive validation
(cache-insights-0to.7) both compose this primitive but emit different verdict
strings. Verdict semantics live in callers; mechanism lives here.

Per-vendor mechanics (per lexicon.prd.md):

- **anthropic**: cross-process. ``claude --resume <session-id> --fork-session``
  launches a new tmux session whose first request reuses the prior session's
  prefix. The original tmux session remains alive for the caller's choice.
- **openai**: cross-process. ``codex fork <session-id>`` launches a new tmux
  session bound to a forked branch of the upstream session.
- **google**: in-process. ``/resume save <tag>`` snapshots the current
  conversation state, ``/resume delete <tag>`` makes the save idempotent
  across re-runs, and ``/resume resume <tag>`` branches into the saved state
  in the same tmux session.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from cache_insights.driver.tmux import TmuxSession


class ForkError(RuntimeError):
    """Raised when a fork primitive cannot be executed.

    Callers (§4.1 / §4.2 test drivers) translate this into either a
    ``verdict=error`` result or a ``byte_identity_broken`` verdict, depending
    on which test is running.
    """


def _claude_session_id() -> str:
    """Find the newest Claude session JSONL under ~/.claude/projects/ and return its stem.

    The stem is the session UUID, which ``claude --resume`` accepts.
    """
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        raise ForkError(f"Claude projects directory not found: {base}")
    jsonls = sorted(
        base.rglob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not jsonls:
        raise ForkError("no Claude session JSONL found under ~/.claude/projects/")
    return jsonls[0].stem


def _codex_session_id() -> str:
    """Return the newest session id from ``codex sessions list --json``."""
    result = subprocess.run(
        ["codex", "sessions", "list", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ForkError(
            f"codex sessions list failed (rc={result.returncode}): "
            f"{result.stderr.strip()}"
        )
    try:
        sessions = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ForkError(f"codex sessions list returned non-JSON: {e}") from e
    if not sessions:
        raise ForkError("codex sessions list returned no sessions")
    first = sessions[0]
    if not isinstance(first, dict) or "id" not in first:
        raise ForkError(f"codex sessions list entry missing 'id': {first!r}")
    return str(first["id"])


def _fork_anthropic(session: TmuxSession, fork_name: str | None) -> TmuxSession:
    session_id = _claude_session_id()
    new_name = fork_name or f"{session.name}-fork-{int(time.time())}"
    new_session = TmuxSession(new_name, session.spec, session.working_dir)
    new_session.launch("--resume", session_id, "--fork-session")
    return new_session


def _fork_openai(session: TmuxSession, fork_name: str | None) -> TmuxSession:
    session_id = _codex_session_id()
    new_name = fork_name or f"{session.name}-fork-{int(time.time())}"
    new_session = TmuxSession(new_name, session.spec, session.working_dir)
    new_session.launch("fork", session_id)
    return new_session


def _fork_google(session: TmuxSession, fork_name: str | None) -> TmuxSession:
    tag = fork_name or f"fork_{int(time.time())}"
    # Idempotent: delete any prior save with the same tag, then save + resume.
    session.send_keys(f"/resume delete {tag}", "Enter")
    time.sleep(0.5)
    session.send_keys(f"/resume save {tag}", "Enter")
    time.sleep(0.5)
    session.send_keys(f"/resume resume {tag}", "Enter")
    time.sleep(0.5)
    return session


_FORKERS = {
    "anthropic": _fork_anthropic,
    "openai": _fork_openai,
    "google": _fork_google,
}


def fork_session(
    session: TmuxSession,
    vendor: str,
    *,
    fork_name: str | None = None,
) -> TmuxSession:
    """Fork an existing vendor CLI session and return a TmuxSession bound to the fork.

    Args:
        session: the live ``TmuxSession`` to fork from.
        vendor: one of ``openai|anthropic|google``.
        fork_name: optional name/tag for the forked session. Defaults to a
            timestamped derivative of ``session.name``.

    Returns:
        A ``TmuxSession`` representing the forked branch. For anthropic and
        openai (cross-process), this is a NEW ``TmuxSession`` instance —
        callers must tear it down separately. For google (in-process), the
        returned object IS the input ``session`` — its conversation state has
        been branched in place.

    Raises:
        ForkError if the vendor is unknown or the fork primitive fails.
    """
    if vendor not in _FORKERS:
        raise ForkError(
            f"Unknown vendor {vendor!r} for fork; "
            f"expected one of {sorted(_FORKERS)}"
        )
    try:
        return _FORKERS[vendor](session, fork_name)
    except ForkError:
        raise
    except Exception as e:  # noqa: BLE001 — wrap arbitrary subprocess/tmux errors
        raise ForkError(f"{type(e).__name__}: {e}") from e


__all__ = ["fork_session", "ForkError"]
