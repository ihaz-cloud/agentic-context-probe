"""Per-vendor token-count helpers.

Each vendor exposes count_tokens(text, model) -> int. Anthropic and Google
provide free count_tokens APIs that are tokenizer-authoritative for the model.
OpenAI does not expose a chat-tokenization endpoint, so we either send a tiny
chat/completions request and read usage.prompt_tokens (authoritative, fractional
cost per call) or fall back to a conservative byte heuristic.

When an API key is missing for a vendor, count_tokens raises RuntimeError —
callers can choose to use estimate_tokens() instead.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from cache_insights._config import load_env_var


HEURISTIC_BYTES_PER_TOKEN = 4
"""Conservative bytes/token ratio for random alphanumeric text. Real BPE
tokenizers (cl100k_base, Claude, Gemini) hit ~3-4 chars/token for ASCII; using
4 over-counts characters → under-estimates tokens on the verification side. For
nonce growth (when no API key is present), we WANT the inverse — over-allocate
characters to ensure target tokens are reached. See estimate_tokens()."""


def estimate_tokens(text: str) -> int:
    """Conservative offline estimate: ~1 token per HEURISTIC_BYTES_PER_TOKEN bytes.

    Useful for sizing payloads when no count_tokens API key is available.
    Always returns an integer; 0 for empty input.
    """
    return max(0, len(text.encode("utf-8")) // HEURISTIC_BYTES_PER_TOKEN)


# -- OpenAI ---------------------------------------------------------------


def _openai_chat_request(payload: dict, api_key: str) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def count_tokens_openai(text: str, model: str = "gpt-4o-mini") -> int:
    """Count tokens via a tiny OpenAI chat completion (returns usage.prompt_tokens).

    Requires OPENAI_API_KEY. The smallest response (max_tokens=1) is requested
    purely to get the prompt's tokenized length back in the usage block. For a
    4096-token nonce on a $2.50/1M-input model, this is about $0.01 per call —
    callers should cache results by content hash.

    Newer OpenAI models (gpt-5, etc) reject `max_tokens` and require
    `max_completion_tokens`. We try `max_tokens` first (works for gpt-4o family);
    on the specific 400 error, we retry with `max_completion_tokens`.
    """
    api_key = load_env_var("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in prd/config.env or environment")
    base = {
        "model": model,
        "messages": [{"role": "user", "content": text}],
    }
    try:
        resp = _openai_chat_request({**base, "max_tokens": 16}, api_key)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        if e.code == 400 and "max_completion_tokens" in body:
            resp = _openai_chat_request({**base, "max_completion_tokens": 16}, api_key)
        else:
            raise RuntimeError(f"OpenAI HTTP {e.code}: {body[:200]}") from e
    usage = resp.get("usage", {})
    if "prompt_tokens" not in usage:
        raise RuntimeError(f"OpenAI response missing usage.prompt_tokens: {resp}")
    return int(usage["prompt_tokens"])


# -- Anthropic ------------------------------------------------------------


def count_tokens_anthropic(text: str, model: str = "claude-haiku-4-5-20251001") -> int:
    """Count tokens via Anthropic's /v1/messages/count_tokens (free, authoritative)."""
    api_key = load_env_var("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in prd/config.env or environment")
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": text}],
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages/count_tokens",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    if "input_tokens" not in resp:
        raise RuntimeError(f"Anthropic response missing input_tokens: {resp}")
    return int(resp["input_tokens"])


# -- Google ---------------------------------------------------------------


def count_tokens_google(text: str, model: str = "gemini-2.5-flash") -> int:
    """Count tokens via Google's models/{model}:countTokens (free, authoritative)."""
    api_key = load_env_var("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in prd/config.env or environment")
    body = json.dumps(
        {"contents": [{"parts": [{"text": text}]}]}
    ).encode()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:countTokens?key={api_key}"
    )
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    if "totalTokens" not in resp:
        raise RuntimeError(f"Google response missing totalTokens: {resp}")
    return int(resp["totalTokens"])


COUNT_TOKENS_BY_VENDOR = {
    "openai": count_tokens_openai,
    "anthropic": count_tokens_anthropic,
    "google": count_tokens_google,
}


def count_tokens(text: str, vendor: str, model: str) -> int:
    """Vendor-dispatched token count.

    Raises ValueError for unknown vendor, RuntimeError if vendor's API key
    is missing.
    """
    if vendor not in COUNT_TOKENS_BY_VENDOR:
        raise ValueError(
            f"Unknown vendor {vendor!r}; expected one of {sorted(COUNT_TOKENS_BY_VENDOR)}"
        )
    return COUNT_TOKENS_BY_VENDOR[vendor](text, model)
