"""§4.1 suffix-variation prefix-stability test driver.

Per vendor:

- turn 1: nonced ~4096-token payload — cold turn
- turn 2: ``"say alpha"`` — warm baseline (validates cache established)
- fork:   the session is forked via ``cache_insights.driver.fork.fork_session``
- turn 3: ``"say bravo"`` on the forked session — post-fork read

Verdict logic (per DESIGN §4.1):

- cold cached_tokens > 0           → contaminated (excluded per DESIGN §8)
- post-fork cached within tolerance of warm baseline → cache_hit_confirmed
- post-fork cached_tokens == 0     → cache_miss (suffix change invalidated cache)
- post-fork cached > 0 but outside tolerance → cache_miss with degraded note
- exception in driver/parser/fork  → error, ``error`` field populated

Validates that vendor caches match on longest common prefix, not on suffix
identity — the property the Context Probe's fork-per-question strategy
depends on.

The fork mechanic is shared with §4.2 (cache-insights-0to.7 fork primitive
validation) via ``cache_insights/driver/fork.py``. This driver emits
``cache_hit_confirmed``/``cache_miss``; 0to.7 emits
``byte_identity_preserved``/``byte_identity_broken`` from the same primitive.
"""

from __future__ import annotations

import time

from cache_insights.driver.dispatch import get_launch_spec
from cache_insights.driver.fork import ForkError, fork_session
from cache_insights.driver.tmux import TmuxSession, driver as driver_ctx
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
POST_FORK_PROMPT = "say bravo"


def _parse_for_vendor(vendor: str, path) -> dict:
    if vendor == "anthropic":
        return VENDOR_PARSER[vendor](jsonl_path=path)
    return VENDOR_PARSER[vendor](path)


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
        test_id=f"{vendor}-suffix_variation-{_slug()}",
        vendor=vendor,
        test_type="suffix_variation",
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


def run_suffix_variation(
    vendor: str,
    model: str,
    *,
    nonce_min_tokens: int = 4096,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    hit_tolerance: float = 0.10,
) -> dict:
    """Run one suffix-variation prefix-stability test for a vendor.

    Args:
        vendor: one of ``openai|anthropic|google``.
        model: vendor-specific model identifier.
        nonce_min_tokens: floor on the nonced cold-prefix payload. Default 4096.
        timeout_s: per-turn completion timeout.
        hit_tolerance: ratio tolerance for declaring post-fork cached_tokens
            equivalent to the warm baseline. Default 10%.

    Returns:
        A §6.1-conformant result dict. Three request entries: ``cold``,
        ``warm_baseline``, ``post_fork``.

    Raises:
        ValueError if vendor is unknown.

    Notes:
        Per DESIGN §8, all in-test failures (CLI launch, tmux, fork mechanism,
        parse, contamination) are captured in the result's ``error``/``verdict``
        fields rather than raised — single-test failures must not abort
        batch runs.
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
    forked_to_teardown: TmuxSession | None = None

    try:
        with driver_ctx(vendor) as session:
            try:
                # ---- COLD turn ------------------------------------------
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

                # ---- WARM BASELINE turn ---------------------------------
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

                # ---- FORK -----------------------------------------------
                forked = fork_session(session, vendor)
                if forked is not session:
                    forked_to_teardown = forked

                # ---- POST_FORK turn (on the forked session) -------------
                baseline = forked.baseline_mtime()
                t0 = time.monotonic()
                forked.send_prompt(POST_FORK_PROMPT)
                post_path = forked.wait_for_completion(
                    baseline_mtime=baseline, timeout=timeout_s
                )
                post_latency_ms = int((time.monotonic() - t0) * 1000)
                post_usage = _parse_for_vendor(vendor, post_path)
                last_usage = post_usage
                requests.append(usage_to_request_entry(
                    post_usage,
                    vendor=vendor,
                    seq=2,
                    label="post_fork",
                    timestamp=now_iso(),
                    latency_ms=post_latency_ms,
                ))
            finally:
                if forked_to_teardown is not None:
                    try:
                        forked_to_teardown.teardown()
                    except Exception:  # noqa: BLE001 — best-effort cleanup
                        pass
    except Exception as e:  # noqa: BLE001 — DESIGN §8 continue-on-failure
        return _error_result(
            vendor=vendor,
            model=model_from_usage(last_usage, model),
            nonce_value=nonce.value,
            nonce_tokens=nonce.token_count,
            requests=requests,
            error_message=f"{type(e).__name__}: {e}",
            started=started,
        )

    cold_cached = requests[0]["cached_tokens"]
    baseline_cached = requests[1]["cached_tokens"]
    post_fork_cached = requests[2]["cached_tokens"]

    if cold_cached > 0:
        verdict = "contaminated"
    elif post_fork_cached == 0:
        verdict = "cache_miss"
    elif compare_hit_ratios(baseline_cached, post_fork_cached, hit_tolerance):
        verdict = "cache_hit_confirmed"
    else:
        # Post-fork cached > 0 but outside tolerance — partial preservation.
        verdict = "cache_miss"

    contaminated = verdict == "contaminated"
    hit_ratio = None
    if verdict == "cache_hit_confirmed":
        inp = requests[2].get("input_tokens", 0)
        if inp > 0:
            hit_ratio = post_fork_cached / inp

    notes_parts: list[str] = []
    if contaminated:
        notes_parts.append(
            f"Cold turn reported cached_tokens={cold_cached} (>0); "
            "excluded per DESIGN §8."
        )
    elif verdict == "cache_miss":
        if post_fork_cached == 0:
            notes_parts.append(
                "Post-fork turn reported cached_tokens=0; suffix change "
                "invalidated the prefix cache. Fork-per-question strategy "
                "would not preserve cached tokens for this vendor/model."
            )
        else:
            notes_parts.append(
                f"Post-fork cached_tokens={post_fork_cached} outside "
                f"{hit_tolerance:.0%} tolerance of warm baseline "
                f"{baseline_cached}; prefix partially preserved. "
                "Treated as miss for verdict purposes."
            )

    resolved_model = model_from_usage(last_usage, model)

    return build_result(
        test_id=f"{vendor}-suffix_variation-{_slug()}",
        vendor=vendor,
        test_type="suffix_variation",
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


__all__ = ["run_suffix_variation", "VENDOR_PARSER", "ForkError"]
