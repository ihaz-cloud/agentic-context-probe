#!/usr/bin/env python3
"""
Quick ad-hoc verification: do local data sources expose cost-complete
usage fields (input_tokens, cached_tokens, output_tokens) per call?

Tests all three vendors:
  1. Claude — reads ~/.claude/projects/<slug>/<uuid>.jsonl
  2. Gemini — reads ~/.gemini/telemetry.log (OTel)
  3. Codex — reads OTel trace file (if configured)

Also makes one direct API call per vendor to capture the response-body
usage block as the reference "what the API actually returns."

Usage:
  python3 verify-local-sources.py

Reads API keys from config.env in the same directory.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_ENV = SCRIPT_DIR / "config.env"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cache_insights.parsers import codex as codex_parser  # noqa: E402
from cache_insights.parsers import gemini as gemini_parser  # noqa: E402


# ---- config.env loader ------------------------------------------------

def load_env_var(name: str) -> str:
    """Read a variable from config.env via bash, falling back to os.environ."""
    val = os.environ.get(name, "").strip()
    if val:
        return val
    if CONFIG_ENV.exists():
        try:
            proc = subprocess.run(
                ["bash", "-c",
                 f"set -a; source '{CONFIG_ENV}'; "
                 f'printf "%s" "${{{name}:-}}"'],
                capture_output=True, text=True, check=True,
            )
            return proc.stdout.strip()
        except subprocess.CalledProcessError:
            pass
    return ""


# ---- Direct API calls --------------------------------------------------

def test_openai_api(api_key: str, nonce: str) -> dict:
    """Send a small prompt to OpenAI Chat Completions, return raw usage."""
    body = json.dumps({
        "model": "gpt-4o-mini",  # cheapest model, just verifying fields
        "messages": [
            {"role": "system", "content": f"nonce: {nonce}"},
            {"role": "user", "content": "say pong"},
        ],
        "max_tokens": 5,
    }).encode()
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


def test_anthropic_api(api_key: str, nonce: str) -> dict:
    """Send a small prompt to Anthropic Messages API, return raw usage."""
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",  # cheapest
        "max_tokens": 5,
        "system": f"nonce: {nonce}",
        "messages": [
            {"role": "user", "content": "say pong"},
        ],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def test_google_api(api_key: str, nonce: str) -> dict:
    """Send a small prompt to Gemini generateContent, return raw response."""
    body = json.dumps({
        "contents": [{"parts": [{"text": f"nonce: {nonce}\nsay pong"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }).encode()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-2.5-flash:generateContent?key={api_key}"
    )
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# ---- Local source readers -----------------------------------------------

def find_latest_claude_jsonl() -> Path | None:
    """Find the most recently modified Claude session JSONL."""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return None
    jsonls = sorted(claude_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return jsonls[-1] if jsonls else None


def read_claude_last_usage(jsonl_path: Path) -> dict | None:
    """Read the last assistant turn's usage block from a Claude JSONL."""
    last_usage = None
    for line in open(jsonl_path):
        try:
            r = json.loads(line)
            if r.get("type") == "assistant" and r.get("message", {}).get("usage"):
                last_usage = r["message"]["usage"]
        except (json.JSONDecodeError, KeyError):
            pass
    return last_usage


def find_codex_otel_file() -> Path | None:
    """Look for Codex OTel trace file. Location depends on config.

    Per DESIGN.prd.md §5.3, the canonical location is the local OTel
    Collector's output file (CODEX_LOGS_FILE). Legacy ~/.codex/ paths are
    kept as fallbacks for older setups.
    """
    candidates = [
        codex_parser.CODEX_LOGS_FILE,
        Path.home() / ".codex" / "otel.log",
        Path.home() / ".codex" / "traces.log",
        Path.home() / ".codex" / "telemetry.log",
        Path.home() / ".codex" / "log" / "otel.log",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p
    log_dir = Path.home() / ".codex" / "log"
    if log_dir.exists():
        for f in sorted(log_dir.iterdir(), key=lambda x: x.stat().st_mtime,
                        reverse=True):
            if f.is_file() and f.stat().st_size < 10_000_000:
                try:
                    text = f.read_text(errors="replace")
                    if "cached_token" in text:
                        return f
                except OSError:
                    pass
    return None


# ---- Main ---------------------------------------------------------------

def main():
    nonce = f"verify-{int(time.time())}-{os.urandom(8).hex()}"
    results = {}

    # --- OpenAI ---
    print("=" * 60)
    print("OPENAI — Direct API usage fields")
    print("=" * 60)
    openai_key = load_env_var("OPENAI_API_KEY")
    if openai_key:
        try:
            resp = test_openai_api(openai_key, nonce)
            usage = resp.get("usage", {})
            print(f"  model:  {resp.get('model')}")
            print(f"  usage keys: {sorted(usage.keys())}")
            print(f"  usage: {json.dumps(usage, indent=4)}")
            results["openai_api"] = usage

            # Check for cached_tokens specifically
            ptd = usage.get("prompt_tokens_details", {})
            print(f"\n  prompt_tokens_details: {json.dumps(ptd, indent=4)}")
            if "cached_tokens" in ptd:
                print(f"  ✓ cached_tokens field PRESENT ({ptd['cached_tokens']})")
            else:
                print(f"  ✗ cached_tokens field MISSING from prompt_tokens_details")
        except Exception as e:
            print(f"  ERROR: {e}")
    else:
        print("  SKIPPED — OPENAI_API_KEY not set")

    # --- Anthropic ---
    print()
    print("=" * 60)
    print("ANTHROPIC — Direct API usage fields")
    print("=" * 60)
    anthropic_key = load_env_var("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            resp = test_anthropic_api(anthropic_key, nonce)
            usage = resp.get("usage", {})
            print(f"  model:  {resp.get('model')}")
            print(f"  usage keys: {sorted(usage.keys())}")
            print(f"  usage: {json.dumps(usage, indent=4)}")
            results["anthropic_api"] = usage

            for field in ["cache_read_input_tokens", "cache_creation_input_tokens",
                          "input_tokens", "output_tokens"]:
                present = field in usage
                print(f"  {'✓' if present else '✗'} {field}: {usage.get(field, 'MISSING')}")
        except Exception as e:
            print(f"  ERROR: {e}")
    else:
        print("  SKIPPED — ANTHROPIC_API_KEY not set")

    # --- Google ---
    print()
    print("=" * 60)
    print("GOOGLE — Direct API usage fields")
    print("=" * 60)
    gemini_key = load_env_var("GEMINI_API_KEY")
    if gemini_key:
        try:
            resp = test_google_api(gemini_key, nonce)
            usage = resp.get("usageMetadata", {})
            print(f"  usageMetadata keys: {sorted(usage.keys())}")
            print(f"  usageMetadata: {json.dumps(usage, indent=4)}")
            results["google_api"] = usage

            for field in ["cachedContentTokenCount", "promptTokenCount",
                          "candidatesTokenCount", "totalTokenCount"]:
                present = field in usage
                print(f"  {'✓' if present else '✗'} {field}: {usage.get(field, 'MISSING')}")
        except Exception as e:
            print(f"  ERROR: {e}")
    else:
        print("  SKIPPED — GEMINI_API_KEY not set")

    # --- Claude local JSONL ---
    print()
    print("=" * 60)
    print("CLAUDE — Local session JSONL usage fields")
    print("=" * 60)
    jsonl = find_latest_claude_jsonl()
    if jsonl:
        print(f"  file: {jsonl}")
        usage = read_claude_last_usage(jsonl)
        if usage:
            print(f"  usage keys: {sorted(usage.keys())}")
            print(f"  usage: {json.dumps(usage, indent=4)}")
            results["claude_local"] = usage
            for field in ["cache_read_input_tokens", "cache_creation_input_tokens",
                          "input_tokens", "output_tokens"]:
                present = field in usage
                print(f"  {'✓' if present else '✗'} {field}: {usage.get(field, 'MISSING')}")
        else:
            print("  No assistant turn with usage found in JSONL")
    else:
        print("  No Claude session JSONL found")

    # --- Gemini local OTel ---
    print()
    print("=" * 60)
    print("GEMINI — Local OTel telemetry fields")
    print("=" * 60)
    tlog = gemini_parser.GEMINI_TELEMETRY_LOG
    if tlog.exists():
        print(f"  file: {tlog}")
        try:
            usage = gemini_parser.parse_last_turn(tlog)
            print(f"  model:  {usage.get('model')}")
            print(f"  usage: {json.dumps(usage, indent=4, default=str)}")
            results["gemini_local"] = usage
            for field in ["input_tokens", "cached_tokens", "output_tokens"]:
                present = field in usage and usage[field] is not None
                print(f"  {'✓' if present else '✗'} {field}: {usage.get(field, 'MISSING')}")
        except (FileNotFoundError, ValueError) as e:
            print(f"  ERROR parsing telemetry log: {e}")
            print(f"  file size: {tlog.stat().st_size} bytes")
            print(f"  Check: is telemetry.enabled = true in ~/.gemini/settings.json?")
            results["gemini_local"] = {"file": str(tlog), "error": str(e)}
    else:
        print(f"  {tlog} does not exist")
        print(f"  To enable: add telemetry.enabled = true to ~/.gemini/settings.json")

    # --- Codex local OTel ---
    print()
    print("=" * 60)
    print("CODEX — Local OTel trace fields")
    print("=" * 60)
    otel_file = find_codex_otel_file()
    if otel_file:
        print(f"  file: {otel_file}")
        try:
            usage = codex_parser.parse_last_turn(otel_file)
            print(f"  model:  {usage.get('model')}")
            print(f"  usage: {json.dumps(usage, indent=4, default=str)}")
            results["codex_local"] = usage
            for field in ["input_tokens", "cached_tokens", "output_tokens"]:
                present = field in usage and usage[field] is not None
                print(f"  {'✓' if present else '✗'} {field}: {usage.get(field, 'MISSING')}")
        except (FileNotFoundError, ValueError) as e:
            print(f"  ERROR parsing collector output: {e}")
            print(f"  file size: {otel_file.stat().st_size} bytes")
            results["codex_local"] = {"file": str(otel_file), "error": str(e)}
    else:
        print(f"  No Codex OTel file found.")
        print(f"  Expected (per DESIGN.prd.md §5.3): {codex_parser.CODEX_LOGS_FILE}")
        print(f"  Also checked legacy paths: ~/.codex/otel.log, ~/.codex/traces.log,")
        print(f"                              ~/.codex/telemetry.log, ~/.codex/log/otel.log")
        print()
        print("  To resolve: start the local OTel Collector (see architecture.md)")
        print("  and run one Codex prompt. Then re-run this script.")
        results["codex_local"] = {"status": "not_found"}

    # --- Summary ---
    print()
    print("=" * 60)
    print("SUMMARY — Cost-complete fields per source")
    print("=" * 60)
    print()
    print("  Source               | input | cached | output | cost-complete?")
    print("  ---------------------|-------|--------|--------|---------------")

    def check(src, in_field, cache_field, out_field):
        if src not in results:
            return "  SKIPPED"
        d = results[src]
        has_in = in_field in d
        has_cache = cache_field in d
        has_out = out_field in d
        complete = has_in and has_cache and has_out
        yi, yc, yo = ("✓" if has_in else "✗"), ("✓" if has_cache else "✗"), ("✓" if has_out else "✗")
        return f"  {yi:5}   {yc:6}   {yo:6}   {'YES' if complete else 'NO'}"

    print(f"  OpenAI API           |{check('openai_api', 'prompt_tokens', 'prompt_tokens_details', 'completion_tokens')}")
    print(f"  Anthropic API        |{check('anthropic_api', 'input_tokens', 'cache_read_input_tokens', 'output_tokens')}")
    print(f"  Google API           |{check('google_api', 'promptTokenCount', 'cachedContentTokenCount', 'candidatesTokenCount')}")
    print(f"  Claude local JSONL   |{check('claude_local', 'input_tokens', 'cache_read_input_tokens', 'output_tokens')}")
    print(f"  Gemini local OTel    |{check('gemini_local', 'input_tokens', 'cached_tokens', 'output_tokens')}")
    print(f"  Codex local OTel     |{check('codex_local', 'input_tokens', 'cached_tokens', 'output_tokens')}")

    # Write raw results
    out_path = SCRIPT_DIR / "verify-local-sources-results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Raw results written to: {out_path}")


if __name__ == "__main__":
    main()
