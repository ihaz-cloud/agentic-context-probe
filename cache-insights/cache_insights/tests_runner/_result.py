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


def compare_hit_ratios(
    baseline_cached: int,
    post_cached: int,
    tolerance: float = 0.10,
) -> bool:
    """Return True if ``post_cached`` is within ``tolerance`` of ``baseline_cached``.

    Used by fork/suffix-variation tests to decide whether a cache survived a
    suffix change. Tolerance accounts for vendor metering noise (default 10%).
    A baseline of 0 returns True only if post is also 0 (degenerate; callers
    typically exclude this via other verdict logic).
    """
    if baseline_cached <= 0:
        return post_cached <= 0
    delta_ratio = abs(post_cached - baseline_cached) / baseline_cached
    return delta_ratio <= tolerance


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
    additional_nonces: list[str] | None = None,
    metrics: dict | None = None,
    cached_at: str | None = None,
    cli_version_source: str | None = None,
) -> dict:
    """Assemble a §6.1 result dict and validate it before returning.

    Multi-payload tests (e.g. content_growth) pass extra nonce values via
    ``additional_nonces``; they are deterministically joined into the schema's
    single ``nonce`` field with ``\\n---NONCE-{B,C,...}---\\n`` separators.
    The first nonce remains nonce_value; subsequent ones are labeled B, C, ...
    """
    if additional_nonces:
        joined = [nonce_value]
        for i, extra in enumerate(additional_nonces, start=1):
            label = chr(ord("A") + i)  # i=1 → B, i=2 → C, ...
            joined.append(f"---NONCE-{label}---")
            joined.append(extra)
        nonce_value = "\n".join(joined)

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
    if metrics is not None:
        record["metrics"] = metrics
    if cached_at is not None:
        record["cached_at"] = cached_at
    if cli_version_source is not None:
        record["cli_version_source"] = cli_version_source
    validate_result(record)
    return record
