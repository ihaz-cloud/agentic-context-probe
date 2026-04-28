"""Shared parser I/O helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator


def iter_pretty_json_records(path: Path) -> Iterator[dict]:
    """Yield JSON records from a file containing pretty-printed (multi-line)
    JSON objects concatenated back-to-back.

    Use this for sources where one logical record spans many lines (e.g. the
    Gemini CLI telemetry log). For sources that emit one JSON record per line
    (Claude session JSONL, Codex OTel collector logs), iterate the file directly.
    """
    text = path.read_text()
    decoder = json.JSONDecoder()
    idx = 0
    n = len(text)
    while idx < n:
        while idx < n and text[idx].isspace():
            idx += 1
        if idx >= n:
            break
        obj, end = decoder.raw_decode(text, idx)
        yield obj
        idx = end


def iter_jsonl_records(path: Path) -> Iterator[dict]:
    """Yield JSON records from a JSONL file (one record per line).

    Silently skips blank lines and unparseable lines.
    """
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
