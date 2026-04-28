"""§4.1 cold/warm pair test driver.

Sends a nonced ≥4096-token user-content payload as turn 1 (cold), sends the
same content as turn 2 (warm) in the same tmux session, and returns a §6.1
result record. Verdict logic (per the bead description):

- cold cached_tokens > 0           → verdict=contaminated, exclude from aggregates
- cold==0, warm cached_tokens > 0  → verdict=cache_hit_confirmed
- cold==0, warm cached_tokens == 0 → verdict=cache_miss (assumption violated)
- exception in driver              → verdict=error, error field populated

The test itself is the experiment that resolves the open question about
tmux+cache reuse — see the bead description for the bounded-assumption rationale.
"""

from __future__ import annotations

import time
from typing import Any

from cache_insights.driver.dispatch import get_launch_spec
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


VENDOR_PARSER = {
    "anthropic": claude_parser.parse_last_turn,
    "openai": codex_parser.parse_last_turn,
    "google": gemini_parser.parse_last_turn,
}


DEFAULT_TIMEOUT_S = 180.0


def _parse_for_vendor(vendor: str, path) -> dict:
    """Dispatch to the vendor-specific parse_last_turn with the right kwarg name."""
    if vendor == "anthropic":
        return VENDOR_PARSER[vendor](jsonl_path=path)
    return VENDOR_PARSER[vendor](path)


def _verdict_for(cold_cached: int, warm_cached: int) -> str:
    if cold_cached > 0:
        return "contaminated"
    if warm_cached > 0:
        return "cache_hit_confirmed"
    return "cache_miss"


def _hit_ratio_for(verdict: str, warm_entry: dict) -> float | None:
    if verdict != "cache_hit_confirmed":
        return None
    inp = warm_entry.get("input_tokens", 0)
    if inp <= 0:
        return None
    return warm_entry["cached_tokens"] / inp


def _slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _error_result(
    *,
    vendor: str,
    model: str,
    nonce_value: str,
    nonce_tokens: int,
    requests: list[dict],
    error_message: str,
    started: str,
) -> dict:
    return build_result(
        test_id=f"{vendor}-cold_warm_pair-{_slug()}",
        vendor=vendor,
        test_type="cold_warm_pair",
        model=model,
        nonce_value=nonce_value,
        nonce_prefix_tokens=nonce_tokens,
        total_payload_tokens=nonce_tokens,
        requests=requests,
        verdict="error",
        error=error_message,
        timestamp_started=started,
        timestamp_completed=now_iso(),
    )


def run_cold_warm_pair(
    vendor: str,
    model: str,
    *,
    nonce_min_tokens: int = 4096,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Run one cold/warm pair test for a vendor, return a §6.1-conformant result.

    Args:
        vendor: one of openai|anthropic|google.
        model: vendor-specific model identifier.
        nonce_min_tokens: minimum tokens for the nonced user-content payload.
            Default 4096 (DESIGN §3 floor).
        timeout_s: per-turn completion timeout.

    Returns:
        A §6.1-conformant result dict, validated before return.

    Raises:
        ValueError if vendor is unknown.

    Notes:
        Per DESIGN §8, all in-test failures (CLI launch, tmux, parse,
        contamination) are captured in the result's `error`/`verdict` fields
        rather than raised — single-test failures must not abort batch runs.
    """
    if vendor not in VENDOR_PARSER:
        raise ValueError(
            f"Unknown vendor {vendor!r}; expected one of {sorted(VENDOR_PARSER)}"
        )

    started = now_iso()
    nonce = generate_nonce(vendor=vendor, model=model, min_tokens=nonce_min_tokens)
    spec = get_launch_spec(vendor)
    requests: list[dict] = []

    try:
        with driver_ctx(vendor) as session:
            # ---- COLD turn ------------------------------------------------
            baseline = session.baseline_mtime()
            t0 = time.monotonic()
            session.send_prompt(nonce.value)
            cold_path = session.wait_for_completion(
                baseline_mtime=baseline, timeout=timeout_s
            )
            cold_latency_ms = int((time.monotonic() - t0) * 1000)
            cold_usage = _parse_for_vendor(vendor, cold_path)
            cold_entry = usage_to_request_entry(
                cold_usage,
                vendor=vendor,
                seq=0,
                label="cold",
                timestamp=now_iso(),
                latency_ms=cold_latency_ms,
            )
            requests.append(cold_entry)

            # ---- WARM turn ------------------------------------------------
            baseline = session.baseline_mtime()
            t0 = time.monotonic()
            session.send_prompt(nonce.value)
            warm_path = session.wait_for_completion(
                baseline_mtime=baseline, timeout=timeout_s
            )
            warm_latency_ms = int((time.monotonic() - t0) * 1000)
            warm_usage = _parse_for_vendor(vendor, warm_path)
            warm_entry = usage_to_request_entry(
                warm_usage,
                vendor=vendor,
                seq=1,
                label="warm",
                timestamp=now_iso(),
                latency_ms=warm_latency_ms,
            )
            requests.append(warm_entry)
    except Exception as e:  # noqa: BLE001 — DESIGN §8 continue-on-failure
        return _error_result(
            vendor=vendor,
            model=model_from_usage({}, model),
            nonce_value=nonce.value,
            nonce_tokens=nonce.token_count,
            requests=requests,
            error_message=f"{type(e).__name__}: {e}",
            started=started,
        )

    cold_cached = requests[0]["cached_tokens"]
    warm_cached = requests[1]["cached_tokens"]
    verdict = _verdict_for(cold_cached, warm_cached)
    contaminated = verdict == "contaminated"
    hit_ratio = _hit_ratio_for(verdict, requests[1])

    notes_parts: list[str] = []
    if contaminated:
        notes_parts.append(
            f"Cold turn reported cached_tokens={cold_cached} (>0); excluded per DESIGN §8."
        )
    elif verdict == "cache_miss":
        notes_parts.append(
            "Warm turn reported cached_tokens=0 with valid cold (==0). "
            "Cache reuse not observed across same-session turns for this vendor/model."
        )

    resolved_model = model_from_usage(warm_usage, model) if requests else model

    return build_result(
        test_id=f"{vendor}-cold_warm_pair-{_slug()}",
        vendor=vendor,
        test_type="cold_warm_pair",
        model=resolved_model,
        nonce_value=nonce.value,
        nonce_prefix_tokens=nonce.token_count,
        total_payload_tokens=nonce.token_count,
        requests=requests,
        verdict=verdict,
        hit_ratio=hit_ratio,
        contaminated=contaminated,
        notes=" ".join(notes_parts),
        timestamp_started=started,
        timestamp_completed=now_iso(),
    )


__all__ = ["run_cold_warm_pair", "VENDOR_PARSER"]
