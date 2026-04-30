"""§4.2 rewind primitive validation test driver.

Per vendor (where supported):

- turn 1: nonced ~4096-token payload — cold turn
- turn 2: ``"say alpha"`` — warm baseline (validates cache established)
- rewind: the session is rewound via ``cache_insights.driver.rewind.rewind_session``
- turn 3: ``"say bravo"`` on the (mutated) session — post-rewind read

Verdict logic (per DESIGN §4.2):

- cold cached_tokens > 0           → contaminated (excluded per DESIGN §8)
- post-rewind cached within tolerance of warm baseline → byte_identity_preserved
- post-rewind cached_tokens == 0   → byte_identity_broken (rewind lost identity)
- post-rewind cached > 0 but outside tolerance → byte_identity_broken w/ degraded note
- ``RewindNotSupported`` raised    → ``verdict="skipped"`` (vendor lacks primitive)
- other exception                  → error, ``error`` field populated

Rewind mutates the current session in-place (no cross-process variant). Vendor
support is non-uniform: only anthropic has a documented Esc-Esc rewind menu.
OpenAI and Google emit ``verdict="skipped"`` with a notes annotation.
"""

from __future__ import annotations

import time

from cache_insights.driver.dispatch import get_launch_spec
from cache_insights.driver.rewind import (
    RewindError,
    RewindNotSupported,
    rewind_session,
)
from cache_insights.driver.tmux import driver as driver_ctx
from cache_insights.nonce import generate_nonce
from cache_insights.parsers import claude as claude_parser
from cache_insights.parsers import codex as codex_parser
from cache_insights.parsers import gemini as gemini_parser
from cache_insights.tests_runner._result import (
    build_result,
    compare_hit_ratios,
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
POST_REWIND_PROMPT = "say bravo"


def _parse_for_vendor(vendor: str, path) -> dict:
    if vendor == "anthropic":
        return VENDOR_PARSER[vendor](jsonl_path=path)
    return VENDOR_PARSER[vendor](path)


def _slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _build(
    *,
    vendor: str,
    model: str,
    nonce_value: str,
    nonce_tokens: int,
    requests: list[dict],
    verdict: str,
    started: str,
    hit_ratio: float | None = None,
    contaminated: bool = False,
    error: str | None = None,
    notes: str = "",
) -> dict:
    return build_result(
        test_id=f"{vendor}-rewind-{_slug()}",
        vendor=vendor,
        test_type="rewind",
        model=model,
        nonce_value=nonce_value,
        nonce_prefix_tokens=nonce_tokens,
        total_payload_tokens=nonce_tokens,
        requests=requests,
        verdict=verdict,
        hit_ratio=hit_ratio,
        contaminated=contaminated,
        error=error,
        notes=notes,
        timestamp_started=started,
        timestamp_completed=now_iso(),
    )


def run_rewind_primitive(
    vendor: str,
    model: str,
    *,
    nonce_min_tokens: int = 4096,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    hit_tolerance: float = 0.10,
) -> dict:
    """Run one rewind-primitive validation test for a vendor.

    Args:
        vendor: one of ``openai|anthropic|google``.
        model: vendor-specific model identifier.
        nonce_min_tokens: floor on the nonced cold-prefix payload.
        timeout_s: per-turn completion timeout.
        hit_tolerance: ratio tolerance for declaring post-rewind cached_tokens
            equivalent to the warm baseline.

    Returns:
        A §6.1-conformant result dict. For supported vendors, three request
        entries: ``cold``, ``warm_baseline``, ``post_rewind``. For unsupported
        vendors, two entries (``cold``, ``warm_baseline``) plus
        ``verdict="skipped"``.

    Raises:
        ValueError if vendor is unknown.
    """
    if vendor not in VENDOR_PARSER:
        raise ValueError(
            f"Unknown vendor {vendor!r}; expected one of {sorted(VENDOR_PARSER)}"
        )

    started = now_iso()
    nonce = generate_nonce(vendor=vendor, model=model, min_tokens=nonce_min_tokens)
    get_launch_spec(vendor)
    requests: list[dict] = []
    last_usage: dict = {}

    try:
        with driver_ctx(vendor) as session:
            # ---- COLD turn --------------------------------------------------
            baseline = session.baseline_mtime()
            t0 = time.monotonic()
            session.send_prompt(nonce.value)
            cold_path = session.wait_for_completion(
                baseline_mtime=baseline, timeout=timeout_s
            )
            cold_latency_ms = int((time.monotonic() - t0) * 1000)
            cold_usage = _parse_for_vendor(vendor, cold_path)
            last_usage = cold_usage
            requests.append(usage_to_request_entry(
                cold_usage,
                vendor=vendor,
                seq=0,
                label="cold",
                timestamp=now_iso(),
                latency_ms=cold_latency_ms,
            ))

            # ---- WARM BASELINE turn -----------------------------------------
            baseline = session.baseline_mtime()
            t0 = time.monotonic()
            session.send_prompt(WARM_BASELINE_PROMPT)
            warm_path = session.wait_for_completion(
                baseline_mtime=baseline, timeout=timeout_s
            )
            warm_latency_ms = int((time.monotonic() - t0) * 1000)
            warm_usage = _parse_for_vendor(vendor, warm_path)
            last_usage = warm_usage
            requests.append(usage_to_request_entry(
                warm_usage,
                vendor=vendor,
                seq=1,
                label="warm_baseline",
                timestamp=now_iso(),
                latency_ms=warm_latency_ms,
            ))

            # ---- REWIND -----------------------------------------------------
            try:
                rewind_session(session, vendor)
            except RewindNotSupported as e:
                # Non-fatal: emit verdict=skipped with what we have so far.
                return _build(
                    vendor=vendor,
                    model=model_from_usage(last_usage, model),
                    nonce_value=nonce.value,
                    nonce_tokens=nonce.token_count,
                    requests=requests,
                    verdict="skipped",
                    started=started,
                    notes=f"rewind primitive not registered for vendor: {e}",
                )

            # ---- POST_REWIND turn -------------------------------------------
            baseline = session.baseline_mtime()
            t0 = time.monotonic()
            session.send_prompt(POST_REWIND_PROMPT)
            post_path = session.wait_for_completion(
                baseline_mtime=baseline, timeout=timeout_s
            )
            post_latency_ms = int((time.monotonic() - t0) * 1000)
            post_usage = _parse_for_vendor(vendor, post_path)
            last_usage = post_usage
            requests.append(usage_to_request_entry(
                post_usage,
                vendor=vendor,
                seq=2,
                label="post_rewind",
                timestamp=now_iso(),
                latency_ms=post_latency_ms,
            ))
    except Exception as e:  # noqa: BLE001 — DESIGN §8 continue-on-failure
        return _build(
            vendor=vendor,
            model=model_from_usage(last_usage, model),
            nonce_value=nonce.value,
            nonce_tokens=nonce.token_count,
            requests=requests,
            verdict="error",
            started=started,
            error=f"{type(e).__name__}: {e}",
        )

    cold_cached = requests[0]["cached_tokens"]
    baseline_cached = requests[1]["cached_tokens"]
    post_rewind_cached = requests[2]["cached_tokens"]

    if cold_cached > 0:
        verdict = "contaminated"
    elif post_rewind_cached == 0:
        verdict = "byte_identity_broken"
    elif compare_hit_ratios(baseline_cached, post_rewind_cached, hit_tolerance):
        verdict = "byte_identity_preserved"
    else:
        verdict = "byte_identity_broken"

    contaminated = verdict == "contaminated"
    hit_ratio = None
    if verdict == "byte_identity_preserved":
        inp = requests[2].get("input_tokens", 0)
        if inp > 0:
            hit_ratio = post_rewind_cached / inp

    notes_parts: list[str] = []
    if contaminated:
        notes_parts.append(
            f"Cold turn reported cached_tokens={cold_cached} (>0); "
            "excluded per DESIGN §8."
        )
    elif verdict == "byte_identity_broken":
        if post_rewind_cached == 0:
            notes_parts.append(
                "Post-rewind turn reported cached_tokens=0; the rewind "
                "primitive did not preserve cached identity for this "
                "vendor/model. UI keystroke sequence may have changed in a "
                "newer CLI version — cross-reference cli_version field."
            )
        else:
            notes_parts.append(
                f"Post-rewind cached_tokens={post_rewind_cached} outside "
                f"{hit_tolerance:.0%} tolerance of warm baseline "
                f"{baseline_cached}; identity partially preserved. "
                "Treated as broken for verdict purposes."
            )

    resolved_model = model_from_usage(last_usage, model)

    return _build(
        vendor=vendor,
        model=resolved_model,
        nonce_value=nonce.value,
        nonce_tokens=nonce.token_count,
        requests=requests,
        verdict=verdict,
        started=started,
        hit_ratio=hit_ratio,
        contaminated=contaminated,
        notes=" ".join(notes_parts),
    )


__all__ = [
    "run_rewind_primitive",
    "VENDOR_PARSER",
    "RewindError",
    "RewindNotSupported",
]
