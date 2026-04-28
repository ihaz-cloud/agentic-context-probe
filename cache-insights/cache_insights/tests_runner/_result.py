"""Helpers for building §6.1-conformant result records from per-vendor parser output.

Each vendor's parse_last_turn returns a slightly different shape — Anthropic
exposes cache_read_input_tokens (not cached_tokens) and adds cache_creation_input_tokens.
This module is the single place that normalizes those shapes into the §6.1 schema.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cache_insights.validate import validate_result


def usage_to_request_entry(
    usage: dict,
    vendor: str,
    *,
    seq: int,
    label: str,
    timestamp: str,
    latency_ms: int | None = None,
) -> dict:
    """Map a per-vendor parse_last_turn dict to a §6.1 request entry.

    Anthropic uses `cache_read_input_tokens`; OpenAI/Google use `cached_tokens`.
    Normalize to the schema's canonical `cached_tokens` field. Anthropic's
    `cache_creation_input_tokens` flows through as the optional schema field
    of the same name.
    """
    if vendor == "anthropic":
        cached = usage.get("cache_read_input_tokens", 0)
        cache_creation = usage.get("cache_creation_input_tokens")
    else:
        cached = usage.get("cached_tokens", 0)
        cache_creation = None

    entry: dict[str, Any] = {
        "seq": seq,
        "label": label,
        "timestamp": timestamp,
        "input_tokens": int(usage.get("input_tokens", 0)),
        "cached_tokens": int(cached or 0),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "raw_usage": _raw_usage_for_record(usage),
    }
    if latency_ms is not None:
        entry["latency_ms"] = int(latency_ms)
    if cache_creation is not None:
        entry["cache_creation_input_tokens"] = int(cache_creation)
    return entry


def _raw_usage_for_record(usage: dict) -> dict:
    """Strip parser-internal fields (e.g. _source_file) from the raw_usage block.

    The schema requires raw_usage to be an object; including the source-file
    path is fine for traceability but we surface it cleanly.
    """
    return {k: v for k, v in usage.items() if not k.startswith("_")}


def model_from_usage(usage: dict, fallback: str) -> str:
    """Prefer the model reported by the local source; fall back to the requested model."""
    return usage.get("model") or fallback


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_result(
    *,
    test_id: str,
    vendor: str,
    test_type: str,
    model: str,
    nonce_value: str,
    nonce_prefix_tokens: int,
    total_payload_tokens: int,
    requests: list[dict],
    verdict: str,
    hit_ratio: float | None = None,
    contaminated: bool = False,
    error: str | None = None,
    notes: str = "",
    timestamp_started: str | None = None,
    timestamp_completed: str | None = None,
    cli_version: str | None = None,
) -> dict:
    """Assemble a §6.1 result dict and validate it before returning."""
    record: dict[str, Any] = {
        "test_id": test_id,
        "vendor": vendor,
        "test_type": test_type,
        "model": model,
        "nonce": nonce_value,
        "nonce_prefix_tokens": int(nonce_prefix_tokens),
        "total_payload_tokens": int(total_payload_tokens),
        "requests": requests,
        "verdict": verdict,
        "contaminated": contaminated,
        "notes": notes,
    }
    if hit_ratio is not None:
        record["hit_ratio"] = float(hit_ratio)
    if error is not None:
        record["error"] = error
    if timestamp_started is not None:
        record["timestamp_started"] = timestamp_started
    if timestamp_completed is not None:
        record["timestamp_completed"] = timestamp_completed
    if cli_version is not None:
        record["cli_version"] = cli_version
    validate_result(record)
    return record
