"""Warmup result cache (per cache-insights-0to.3).

The §4.1 prefix-warmup test is expensive — multiple turns against a real CLI
plus tokenizer verification. Its output (CLI overhead, cache engagement turn,
hit ratio per turn) is stable per (vendor, model, cli_version), so we cache
the §6.1 result on disk and reuse it on subsequent runs unless any of those
three change.

Cache file format: a §6.1 result dict (already validated) plus two extra
top-level fields:

- ``cached_at``: ISO-8601 timestamp when the cache was written
- ``cli_version_source``: verbatim stdout of the vendor's --version command,
  for traceability across CLI version drift

Files live at::

    $XDG_CACHE_HOME/cache-insights/warmup/<vendor>__<model>__<cli_version>.json

(falling back to ``~/.cache/cache-insights/warmup/`` if XDG_CACHE_HOME is unset).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

CACHE_SUBDIR = "cache-insights/warmup"
_PART_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _xdg_cache_home() -> Path:
    """Honor XDG_CACHE_HOME; fall back to ~/.cache."""
    env = os.environ.get("XDG_CACHE_HOME")
    if env:
        return Path(env)
    return Path.home() / ".cache"


def _sanitize_part(part: str) -> str:
    """Make a path part filename-safe by replacing risky chars with ``_``."""
    return _PART_SAFE_RE.sub("_", part)


def cache_path_for(vendor: str, model: str, cli_version: str) -> Path:
    """Return the canonical cache file path for the (vendor, model, cli_version) tuple."""
    fname = (
        f"{_sanitize_part(vendor)}__"
        f"{_sanitize_part(model)}__"
        f"{_sanitize_part(cli_version)}.json"
    )
    return _xdg_cache_home() / CACHE_SUBDIR / fname


def load_cached(path: Path) -> dict | None:
    """Return the cached result dict, or None if missing / unreadable / malformed."""
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def write_cached(path: Path, result: dict) -> None:
    """Atomically write ``result`` to ``path``.

    Parent directory is created on demand. The write goes to a tempfile in
    the same directory, then ``os.replace`` swaps it into place — so a
    mid-write crash leaves any prior cache file intact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(result, f, indent=2, sort_keys=True)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup of orphaned tempfile.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


__all__ = ["cache_path_for", "load_cached", "write_cached"]
