# Lessons Learned — Cache Insights

Findings from the April 2026 investigation into cross-vendor prompt cache verification. Each lesson documents an assumption that turned out to be wrong, what we discovered, and how it changed the system design.

## Lessons

1. **[Admin APIs are not needed](admin-api-not-needed.md)** — All three CLIs expose per-call cache attribution locally (Claude JSONL, Gemini OTel, Codex OTel). The admin API polling infrastructure we built was unnecessary. Always check local files before building external polling.

2. **[Byte-identical fixtures contaminate baselines](methodology-contamination.md)** — Sending the same prompt bytes across runs hits the server-side prefix cache from prior runs, inflating "cold" baselines to 64-73% cache hit. Fixed with per-test nonce injection.

3. **[Cache mechanics should use direct API, not the CLI](cli-vs-direct-api.md)** — The CLI adds uncontrollable bytes (system prompts, tool definitions) to every request. Cache mechanics testing needs exact byte control, which only direct API calls provide. CLI is reserved for the narrow question of whether fork/rewind primitives preserve cache.

## How these lessons shaped the design

| Before | After |
|---|---|
| Admin API pre/post snapshot polling with 5-min lag waits | Local file reads with zero lag |
| Same fixture bytes across all runs | Unique nonce per test case, contamination assertion |
| CLI-driven scenarios A/B/C/D/E for all cache questions | Direct API for mechanics, CLI only for 6 primitive tests |
| Three harness classes + OpTimer + footer parsing + ANSI stripping | ~200 lines of direct HTTP calls + local file parsers |
