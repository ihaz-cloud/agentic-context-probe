# Lesson: Admin APIs are not needed for cache attribution

**Date:** April 2026
**Status:** Resolved — admin API polling infrastructure removed from DESIGN.prd.md

## What we assumed

All three vendors' admin/usage APIs were required to get per-call cache attribution:
- OpenAI: `GET /v1/organization/usage/completions` with `sk-admin-` key
- Anthropic: `GET /v1/organizations/usage_report/messages` with `sk-ant-admin01-` key  
- Google: no admin API exists (documented as vendor capability gap)

We built pre/post snapshot polling, 5-minute aggregation lag waits, retry ladders for 5xx errors, project/workspace filters, and auth-mode preflight checks to detect when the CLI was using OAuth instead of API-key auth (which made admin API data invisible).

## What we discovered

All three CLIs expose per-call cache attribution **locally** with zero lag:

| CLI | Source | Fields | Opt-in |
|---|---|---|---|
| Claude Code | `~/.claude/projects/<slug>/<uuid>.jsonl` | `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens`, TTL tier, service_tier, inference_geo | None — always written |
| Gemini CLI | `~/.gemini/telemetry.log` (OTel) | `input_token_count`, `output_token_count`, `cached_content_token_count` | `telemetry.enabled: true` + `target: "local"` in settings.json |
| Codex CLI | OTel logs via OTLP to local collector | `input_token_count`, `output_token_count`, `cached_token_count`, `reasoning_token_count`, `tool_token_count` | `[otel.trace_exporter.otlp-http]` in config.toml + local OTel Collector |

All three are cost-complete — they provide the full set of fields needed to compute exact dollar cost per call without any external API.

## Why the admin API path was built

1. We didn't know the local sources existed when the test-cache scripts were first written
2. The CLI TUI footer counters (which we DID know about) don't split cached vs uncached — they show totals only
3. The admin API was the only documented path to `input_cached_tokens` per vendor
4. We assumed "the CLI consumes the response body and doesn't save the usage block anywhere"

All four assumptions turned out to be wrong for at least some vendors.

## What we removed from the PRD

- References to admin API as a required evidence source for §4.1 and §4.2
- `sk-admin-` and `sk-ant-admin01-` key requirements
- Pre/post snapshot polling pattern with aggregation lag waits
- Retry ladders for transient 5xx HTTP errors on admin endpoints
- Project ID / workspace ID filtering on admin queries
- Auth-mode preflight warnings about OAuth vs API-key auth (the local sources work regardless of auth mode)

## What we kept

- The `OPENAI_ADMIN_API_KEY` and `ANTHROPIC_ADMIN_API_KEY` fields in `config.env` — they may be useful for Goal 2 (context-probe) billing cross-checks on expensive runs
- The admin API documentation in `research.md` — still accurate vendor reference material
- The auth-mode findings (ChatGPT OAuth vs API-key auth) — documented in research.md as a lesson learned, not as a system requirement

## The meta-lesson

**Always check what the CLI writes to disk before building an external polling path.** The local sources were there all along — we just didn't look because the admin API was the "obvious" answer from the vendor docs. Three weeks of admin API infrastructure (auth provisioning, key rotation, lag tuning, retry logic, project filtering) could have been replaced by reading a local file on day one.

For future vendors added to the system: check for local session files, OTel export, and debug logs BEFORE reaching for an admin API. The local path is faster (zero lag), cheaper (no admin key provisioning), simpler (file read vs HTTP polling), and works regardless of the operator's auth mode.
