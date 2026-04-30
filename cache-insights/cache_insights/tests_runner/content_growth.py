"""§4.1 content-growth prefix-stability test driver.

Per vendor in a single same-process tmux session:
- turn 1: nonced payload A (~4096 tokens) — cold turn
- turn 2: "say alpha" — warm baseline (validates cache established)
- turn 3: additional nonced payload B (~2048 tokens) — append turn
- turn 4: "say bravo" — post-growth read

Verdict logic (per DESIGN §4.1):

- cold cached_tokens > 0           → contaminated (excluded per DESIGN §8)
- cold==0, post_growth cached > 0  → cache_hit_confirmed (prefix survives append)
- cold==0, post_growth cached == 0 → cache_miss (prefix invalidated by append)
- exception in driver/parser       → error, error field populated

Validates the Context Probe's incremental tier-loading assumption: appending
Tier N+1 content does not invalidate the Tier N prefix cache. Falsification
forces tier-reload-per-question rather than incremental load.
"""

from __future__ import annotations

import time

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
WARM_BASELINE_PROMPT = "say alpha"
POST_GROWTH_PROMPT = "say bravo"


def _parse_for_vendor(vendor: str, path) -> dict:
    """Dispatch to the vendor-specific parse_last_turn with the right kwarg name."""
    if vendor == "anthropic":
        return VENDOR_PARSER[vendor](jsonl_path=path)
    return VENDOR_PARSER[vendor](path)


def _verdict_for(cold_cached: int, post_growth_cached: int) -> str:
    if cold_cached > 0:
        return "contaminated"
    if post_growth_cached > 0:
        return "cache_hit_confirmed"
    return "cache_miss"


def _hit_ratio_for(verdict: str, post_entry: dict) -> float | None:
    if verdict != "cache_hit_confirmed":
        return None
    inp = post_entry.get("input_tokens", 0)
    if inp <= 0:
        return None
    return post_entry["cached_tokens"] / inp


def _slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _error_result(
    *,
    vendor: str,
    model: str,
    nonce_a_value: str,
    nonce_b_value: str,
    nonce_a_tokens: int,
    nonce_b_tokens: int,
    requests: list[dict],
    error_message: str,
    started: str,
) -> dict:
    return build_result(
        test_id=f"{vendor}-content_growth-{_slug()}",
        vendor=vendor,
        test_type="content_growth",
        model=model,
        nonce_value=nonce_a_value,
        nonce_prefix_tokens=nonce_a_tokens,
        total_payload_tokens=nonce_a_tokens + nonce_b_tokens,
        requests=requests,
        verdict="error",
        error=error_message,
        timestamp_started=started,
        timestamp_completed=now_iso(),
        additional_nonces=[nonce_b_value],
    )


_TURN_PLAN = [
    ("cold", None),            # placeholder: nonce A inserted at runtime
    ("warm_baseline", WARM_BASELINE_PROMPT),
    ("growth_t2", None),       # placeholder: nonce B inserted at runtime
    ("post_growth", POST_GROWTH_PROMPT),
]


def run_content_growth(
    vendor: str,
    model: str,
    *,
    nonce_a_min_tokens: int = 4096,
    nonce_b_min_tokens: int = 2048,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Run one content-growth prefix-stability test for a vendor.

    Args:
        vendor: one of openai|anthropic|google.
        model: vendor-specific model identifier.
        nonce_a_min_tokens: floor on nonce A (the cold prefix). Default 4096.
        nonce_b_min_tokens: floor on nonce B (the appended growth). Default 2048.
        timeout_s: per-turn completion timeout.

    Returns:
        A §6.1-conformant result dict, validated before return. The result's
        ``nonce`` field is the joined string ``"<a>\\n---NONCE-B---\\n<b>"``;
        ``nonce_prefix_tokens`` is nonce A only; ``total_payload_tokens`` is
        the sum across both nonces.

    Raises:
        ValueError if vendor is unknown.

    Notes:
        Per DESIGN §8, all in-test failures (CLI launch, tmux, parse,
        contamination) are captured in the result's ``error`` / ``verdict``
        fields rather than raised — single-test failures must not abort
        batch runs.
    """
    if vendor not in VENDOR_PARSER:
        raise ValueError(
            f"Unknown vendor {vendor!r}; expected one of {sorted(VENDOR_PARSER)}"
        )

    started = now_iso()
    nonce_a = generate_nonce(vendor=vendor, model=model, min_tokens=nonce_a_min_tokens)
    nonce_b = generate_nonce(vendor=vendor, model=model, min_tokens=nonce_b_min_tokens)
    get_launch_spec(vendor)  # validate launch spec is registered (parity with cold_warm)
    requests: list[dict] = []
    last_usage: dict = {}

    prompts = {
        "cold": nonce_a.value,
        "growth_t2": nonce_b.value,
    }

    try:
        with driver_ctx(vendor) as session:
            for seq, (label, fixed_prompt) in enumerate(_TURN_PLAN):
                prompt = fixed_prompt if fixed_prompt is not None else prompts[label]
                baseline = session.baseline_mtime()
                t0 = time.monotonic()
                session.send_prompt(prompt)
                completion_path = session.wait_for_completion(
                    baseline_mtime=baseline, timeout=timeout_s
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                usage = _parse_for_vendor(vendor, completion_path)
                last_usage = usage
                entry = usage_to_request_entry(
                    usage,
                    vendor=vendor,
                    seq=seq,
                    label=label,
                    timestamp=now_iso(),
                    latency_ms=latency_ms,
                )
                requests.append(entry)
    except Exception as e:  # noqa: BLE001 — DESIGN §8 continue-on-failure
        return _error_result(
            vendor=vendor,
            model=model_from_usage(last_usage, model),
            nonce_a_value=nonce_a.value,
            nonce_b_value=nonce_b.value,
            nonce_a_tokens=nonce_a.token_count,
            nonce_b_tokens=nonce_b.token_count,
            requests=requests,
            error_message=f"{type(e).__name__}: {e}",
            started=started,
        )

    cold_cached = requests[0]["cached_tokens"]
    post_growth_cached = requests[3]["cached_tokens"]
    verdict = _verdict_for(cold_cached, post_growth_cached)
    contaminated = verdict == "contaminated"
    hit_ratio = _hit_ratio_for(verdict, requests[3])

    notes_parts: list[str] = []
    if contaminated:
        notes_parts.append(
            f"Cold turn reported cached_tokens={cold_cached} (>0); excluded per DESIGN §8."
        )
    elif verdict == "cache_miss":
        notes_parts.append(
            "Post-growth turn reported cached_tokens=0 with valid cold (==0). "
            "Prefix cache invalidated by content append — incremental "
            "tier-loading assumption falsified for this vendor/model."
        )
        if vendor == "anthropic":
            notes_parts.append(
                "Anthropic auto-places cache_control on the last block; "
                "post-growth miss may indicate the marker shifted from nonce A "
                "to nonce B — cross-reference §4.2 cache_control investigation."
            )

    resolved_model = model_from_usage(last_usage, model)

    return build_result(
        test_id=f"{vendor}-content_growth-{_slug()}",
        vendor=vendor,
        test_type="content_growth",
        model=resolved_model,
        nonce_value=nonce_a.value,
        nonce_prefix_tokens=nonce_a.token_count,
        total_payload_tokens=nonce_a.token_count + nonce_b.token_count,
        requests=requests,
        verdict=verdict,
        hit_ratio=hit_ratio,
        contaminated=contaminated,
        notes=" ".join(notes_parts),
        timestamp_started=started,
        timestamp_completed=now_iso(),
        additional_nonces=[nonce_b.value],
    )


__all__ = ["run_content_growth", "VENDOR_PARSER"]
