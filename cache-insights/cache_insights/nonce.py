"""Per-test nonce generator.

Produces deterministic-from-seed, semantically-inert payloads of >= min_tokens
when tokenized by a target vendor's model. The nonce is recorded verbatim in
each result file for contamination tracing (DESIGN §3).

Usage:
    nonce = generate_nonce(vendor="openai", model="gpt-5.3", min_tokens=4096)
    # nonce.value: the payload string
    # nonce.token_count: actual tokens (verified if API key present, else estimated)
    # nonce.is_verified: True iff verified by the vendor's count_tokens API
"""

from __future__ import annotations

import hashlib
import json
import random
import string
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from cache_insights.tokenizers import (
    COUNT_TOKENS_BY_VENDOR,
    estimate_tokens,
)

DEFAULT_MIN_TOKENS = 4096
DEFAULT_CACHE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "nonce-cache.json"

# Random-alphanumeric chunk size. 64-char chunks tokenize to ~16-20 tokens
# under typical BPE — small enough to grow precisely, large enough that the
# loop converges fast.
CHUNK_LEN = 64
CHUNK_ALPHABET = string.ascii_lowercase + string.ascii_uppercase + string.digits


@dataclass
class Nonce:
    """A test nonce + its verification metadata.

    `value` is recorded verbatim in result files. `token_count` is authoritative
    when `is_verified=True`, otherwise it's a conservative estimate.
    """
    value: str
    token_count: int
    vendor: str
    model: str
    seed: str
    is_verified: bool
    content_hash: str = field(default="")

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                f"{self.value}|{self.vendor}|{self.model}".encode()
            ).hexdigest()


def _emit_chunk(rng: random.Random) -> str:
    return "".join(rng.choices(CHUNK_ALPHABET, k=CHUNK_LEN)) + " "


def _content_hash(value: str, vendor: str, model: str) -> str:
    return hashlib.sha256(f"{value}|{vendor}|{model}".encode()).hexdigest()


def _load_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text())
    except json.JSONDecodeError:
        return {}


def _write_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def generate_nonce(
    vendor: str,
    model: str,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    seed: str | None = None,
    cache_path: Path | None = None,
    verify: bool = True,
) -> Nonce:
    """Generate a nonce of >= min_tokens for the (vendor, model) tokenizer.

    Args:
        vendor: one of openai|anthropic|google.
        model: vendor-specific model identifier.
        min_tokens: floor on tokenized length. Default 4096 per DESIGN §3.
        seed: optional seed string for reproducibility. Defaults to a fresh UUID4.
        cache_path: where to record verified token counts (avoids repeat API calls).
            Defaults to tests/fixtures/nonce-cache.json.
        verify: if True (default) and the vendor's API key is present, call the
            vendor's count_tokens API for an authoritative count. If False, only
            the heuristic estimate is used.

    Returns:
        Nonce with value, token_count, is_verified, and metadata.

    Raises:
        ValueError for unknown vendor.
    """
    if vendor not in COUNT_TOKENS_BY_VENDOR:
        raise ValueError(
            f"Unknown vendor {vendor!r}; expected one of {sorted(COUNT_TOKENS_BY_VENDOR)}"
        )

    seed = seed or str(uuid.uuid4())
    rng = random.Random(seed)
    cache_path = cache_path or DEFAULT_CACHE_PATH

    # Phase 1: grow heuristically until estimate >= min_tokens.
    parts: list[str] = []
    while estimate_tokens("".join(parts)) < min_tokens:
        parts.append(_emit_chunk(rng))
    value = "".join(parts).rstrip() + "\n"

    estimated = estimate_tokens(value)

    # Phase 2: verify via API if requested and key is available; cache result.
    is_verified = False
    token_count = estimated
    if verify:
        cache = _load_cache(cache_path)
        chash = _content_hash(value, vendor, model)
        if chash in cache:
            token_count = int(cache[chash]["token_count"])
            is_verified = bool(cache[chash].get("verified", False))
        else:
            try:
                fn = COUNT_TOKENS_BY_VENDOR[vendor]
                token_count = fn(value, model)
                is_verified = True
                cache[chash] = {
                    "vendor": vendor,
                    "model": model,
                    "token_count": token_count,
                    "verified": True,
                }
                _write_cache(cache_path, cache)
            except RuntimeError:
                # API key missing — keep estimate, do not cache (future runs may have key)
                is_verified = False

    # Phase 3: if verified count is below the floor, regrow.
    while is_verified and token_count < min_tokens:
        parts.append(_emit_chunk(rng))
        value = "".join(parts).rstrip() + "\n"
        chash = _content_hash(value, vendor, model)
        cache = _load_cache(cache_path)
        if chash in cache:
            token_count = int(cache[chash]["token_count"])
        else:
            fn = COUNT_TOKENS_BY_VENDOR[vendor]
            token_count = fn(value, model)
            cache[chash] = {
                "vendor": vendor,
                "model": model,
                "token_count": token_count,
                "verified": True,
            }
            _write_cache(cache_path, cache)

    return Nonce(
        value=value,
        token_count=token_count,
        vendor=vendor,
        model=model,
        seed=seed,
        is_verified=is_verified,
    )
