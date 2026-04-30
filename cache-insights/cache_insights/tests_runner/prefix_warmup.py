"""§4.1 prefix warmup + meter calibration test driver.

Per vendor in a single same-process tmux session:

- turn 1: a unique ~128-token payload (cold)
- turn 2..N (default 8): each turn appends a fresh ~128-512 token increment to
  the cumulative user-content payload

After every turn we record (input_tokens, cached_tokens, expected_user_content
_tokens). The output ``metrics`` block computes:

- ``overhead_per_turn[i]``: ``input_tokens[i] - expected_user_content_per_turn[i]``
  — the CLI's hidden overhead (system prompt + tool defs)
- ``first_cache_engagement_turn``: smallest i where cached_tokens > 0
- ``hit_ratio_per_turn[i]``: ``cached_tokens[i] / input_tokens[i]``
- ``expected_user_content_per_turn[i]``: cumulative count of user-content
  tokens through turn i

Result is cached per ``(vendor, model, cli_version)``; reuse on subsequent
runs unless any of the three change. Operator can force a fresh warmup via
``force_fresh=True``. The cached file is operator-readable plain JSON.

Caching invariants:

- Cache hit + ``force_fresh=False`` → return cached result with verdict
  injected as ``"skipped"`` and notes citing the cache path.
- ``cli_version`` returns ``"unknown"`` → run executes but cache is NOT
  written (cannot key it).
- verdict is ``contaminated`` (turn 1 cached > 0) → cache NOT written.
- verdict is ``error`` (driver/parser failure) → cache NOT written.

This driver consumes:

- ``cache_insights.driver.dispatch.cli_version`` — version-string detection
- ``cache_insights.tests_runner._warmup_cache`` — cache I/O helpers
- ``cache_insights.tests_runner._result.build_result`` — §6.1 result builder
"""

from __future__ import annotations

import time

from cache_insights.driver.dispatch import cli_version, get_launch_spec
from cache_insights.driver.tmux import driver as driver_ctx
from cache_insights.nonce import generate_nonce
from cache_insights.parsers import claude as claude_parser
from cache_insights.parsers import codex as codex_parser
from cache_insights.parsers import gemini as gemini_parser
from cache_insights.tests_runner._result import (
    build_result,
    model_from_usage,
    now_iso,
    usage_to_request_entry,
)
from cache_insights.tests_runner._warmup_cache import (
    cache_path_for,
    load_cached,
    write_cached,
)


VENDOR_PARSER = {
    "anthropic": claude_parser.parse_last_turn,
    "openai": codex_parser.parse_last_turn,
    "google": gemini_parser.parse_last_turn,
}


DEFAULT_TIMEOUT_S = 180.0


def _parse_for_vendor(vendor: str, path) -> dict:
    if vendor == "anthropic":
        return VENDOR_PARSER[vendor](jsonl_path=path)
    return VENDOR_PARSER[vendor](path)


def _slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _compute_metrics(
    requests: list[dict], expected_user_content_per_turn: list[int]
) -> dict:
    """Build the ``metrics`` block from per-turn requests + expected token counts."""
    overhead = [
        int(r["input_tokens"]) - int(expected_user_content_per_turn[i])
        for i, r in enumerate(requests)
    ]
    first_engagement: int | None = None
    for i, r in enumerate(requests):
        if int(r["cached_tokens"]) > 0:
            first_engagement = i
            break
    hit_ratios = [
        (int(r["cached_tokens"]) / int(r["input_tokens"]))
        if int(r["input_tokens"]) > 0
        else 0.0
        for r in requests
    ]
    return {
        "overhead_per_turn": overhead,
        "first_cache_engagement_turn": first_engagement,
        "hit_ratio_per_turn": hit_ratios,
        "expected_user_content_per_turn": list(expected_user_content_per_turn),
    }


def run_prefix_warmup(
    vendor: str,
    model: str,
    *,
    initial_tokens: int = 128,
    increment_min_tokens: int = 128,
    increment_max_tokens: int = 512,
    num_turns: int = 8,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cache_path=None,
    force_fresh: bool = False,
) -> dict:
    """Run one prefix-warmup + meter-calibration test for a vendor.

    Args:
        vendor: one of ``openai|anthropic|google``.
        model: vendor-specific model identifier.
        initial_tokens: floor on the first-turn payload. Default 128.
        increment_min_tokens: floor on per-turn append payload. Default 128.
        increment_max_tokens: ceiling for per-turn append (advisory; nonce
            generator may exceed if tokenizer disagrees). Default 512.
        num_turns: total number of turns including turn 1. Default 8.
        timeout_s: per-turn completion timeout.
        cache_path: optional override for the warmup cache file path. If None,
            the canonical path is computed from cli_version().
        force_fresh: if True, bypass the cache (delete + re-run). Default False.

    Returns:
        A §6.1-conformant result dict including a ``metrics`` block.
        Cache hits return the cached dict with ``verdict="skipped"`` and
        ``notes`` citing the cache path.

    Raises:
        ValueError if vendor is unknown.
    """
    if vendor not in VENDOR_PARSER:
        raise ValueError(
            f"Unknown vendor {vendor!r}; expected one of {sorted(VENDOR_PARSER)}"
        )

    detected_version = cli_version(vendor)
    resolved_cache_path = cache_path
    if resolved_cache_path is None and detected_version != "unknown":
        resolved_cache_path = cache_path_for(vendor, model, detected_version)

    # ---- Cache hit short-circuit -----------------------------------------
    if (
        not force_fresh
        and resolved_cache_path is not None
        and resolved_cache_path.exists()
    ):
        cached = load_cached(resolved_cache_path)
        if cached is not None:
            cached["verdict"] = "skipped"
            existing_notes = cached.get("notes") or ""
            cite = f"loaded from warmup cache {resolved_cache_path}"
            cached["notes"] = (
                f"{existing_notes} {cite}".strip() if existing_notes else cite
            )
            return cached

    started = now_iso()
    get_launch_spec(vendor)
    requests: list[dict] = []
    expected_user_content_per_turn: list[int] = []
    last_usage: dict = {}
    nonces: list = []
    cumulative_tokens = 0

    try:
        with driver_ctx(vendor) as session:
            for turn_idx in range(num_turns):
                if turn_idx == 0:
                    nonce_min = initial_tokens
                else:
                    # Use the floor; nonce generator targets >= min_tokens.
                    nonce_min = increment_min_tokens
                turn_nonce = generate_nonce(
                    vendor=vendor, model=model, min_tokens=nonce_min
                )
                nonces.append(turn_nonce)
                cumulative_tokens += turn_nonce.token_count
                expected_user_content_per_turn.append(cumulative_tokens)

                baseline = session.baseline_mtime()
                t0 = time.monotonic()
                session.send_prompt(turn_nonce.value)
                completion_path = session.wait_for_completion(
                    baseline_mtime=baseline, timeout=timeout_s
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                usage = _parse_for_vendor(vendor, completion_path)
                last_usage = usage
                requests.append(usage_to_request_entry(
                    usage,
                    vendor=vendor,
                    seq=turn_idx,
                    label=f"turn_{turn_idx}",
                    timestamp=now_iso(),
                    latency_ms=latency_ms,
                ))
    except Exception as e:  # noqa: BLE001 — DESIGN §8 continue-on-failure
        nonce_repr = _join_nonces(nonces) or "<no nonces generated before failure>"
        return build_result(
            test_id=f"{vendor}-prefix_warmup-{_slug()}",
            vendor=vendor,
            test_type="prefix_warmup",
            model=model_from_usage(last_usage, model),
            nonce_value=nonce_repr,
            nonce_prefix_tokens=nonces[0].token_count if nonces else 0,
            total_payload_tokens=cumulative_tokens,
            requests=requests,
            verdict="error",
            error=f"{type(e).__name__}: {e}",
            timestamp_started=started,
            timestamp_completed=now_iso(),
        )

    # ---- Verdict + metrics -----------------------------------------------
    cold_cached = requests[0]["cached_tokens"] if requests else 0
    contaminated = cold_cached > 0
    if contaminated:
        verdict = "contaminated"
    else:
        verdict = "completed"

    metrics = _compute_metrics(requests, expected_user_content_per_turn)

    notes_parts: list[str] = []
    if contaminated:
        notes_parts.append(
            f"Turn 0 reported cached_tokens={cold_cached} (>0); excluded per DESIGN §8."
        )
    if detected_version == "unknown":
        notes_parts.append(
            "cli_version detection returned 'unknown'; result NOT written to cache."
        )

    resolved_model = model_from_usage(last_usage, model)

    additional = [n.value for n in nonces[1:]] if len(nonces) > 1 else None

    record = build_result(
        test_id=f"{vendor}-prefix_warmup-{_slug()}",
        vendor=vendor,
        test_type="prefix_warmup",
        model=resolved_model,
        nonce_value=nonces[0].value if nonces else "",
        nonce_prefix_tokens=nonces[0].token_count if nonces else 0,
        total_payload_tokens=cumulative_tokens,
        requests=requests,
        verdict=verdict,
        contaminated=contaminated,
        notes=" ".join(notes_parts),
        timestamp_started=started,
        timestamp_completed=now_iso(),
        cli_version=detected_version if detected_version != "unknown" else None,
        metrics=metrics,
        additional_nonces=additional,
    )

    # ---- Cache write (skip on contaminated/error/unknown-version) --------
    if (
        verdict == "completed"
        and not contaminated
        and detected_version != "unknown"
        and resolved_cache_path is not None
    ):
        cache_record = dict(record)
        cache_record["cached_at"] = now_iso()
        cache_record["cli_version_source"] = detected_version
        try:
            write_cached(resolved_cache_path, cache_record)
        except Exception:  # noqa: BLE001 — cache write is best-effort
            # Don't fail the test on cache-write issues; the result is still valid.
            pass

    return record


def _join_nonces(nonces: list) -> str:
    """Join nonce values with the same separator convention as build_result."""
    if not nonces:
        return ""
    if len(nonces) == 1:
        return nonces[0].value
    parts = [nonces[0].value]
    for i, n in enumerate(nonces[1:], start=1):
        label = chr(ord("A") + i)
        parts.append(f"---NONCE-{label}---")
        parts.append(n.value)
    return "\n".join(parts)


__all__ = ["run_prefix_warmup", "VENDOR_PARSER"]
