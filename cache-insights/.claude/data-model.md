# Data Model Reference

Purpose: This system has no relational database. The "data model" is the JSON schemas of test results, the TOML schema of the pricing table, and the JSON schema of the cost forecast. Read `architecture.md` first for context.

---

## Entity Relationship Overview

```
┌─────────────────┐      ┌─────────────────┐
│  pricing.toml   │      │   config.env    │
│  per-vendor +   │      │  model defaults │
│  per-model      │      │  vendor secrets │
│  rates          │      └────────┬────────┘
└────────┬────────┘               │
         │                        │
         │      ┌─────────────────▼──────────────────┐
         │      │  Cache test component              │
         │      │  - generates nonce per test case   │
         │      │  - drives vendor CLI via tmux      │
         │      │  - reads local attribution source  │
         │      └─────────────────┬──────────────────┘
         │                        │
         │              ┌─────────▼──────────┐
         │              │  results/*.json    │
         │              │  (§6.1 per-test    │
         │              │   result records)  │
         │              └─────────┬──────────┘
         │                        │
         └────────────┬───────────┘
                      │
            ┌─────────▼──────────┐
            │ Cost forecast      │
            │ (§6.3 forecast     │
            │  output records)   │
            └────────────────────┘
```

Records are flat JSON; there is no DB, no migrations, no ORM.

---

## Per-Test Result Schema (§6.1)

Each test case produces one JSON file in `results/`. Vendor, test_type, and verdict appear at the top level so the file is human-readable without tooling.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `test_id` | string | yes | `<vendor>-<test_type>-<timestamp>-<short-id>` |
| `vendor` | enum | yes | `openai` \| `anthropic` \| `google` |
| `test_type` | enum | yes | `cold_warm_pair` \| `ttl_mapping` \| `prefix_warmup` \| `suffix_variation` \| `content_growth` \| `efficiency_measurement` \| `primitive_fork` \| `primitive_rewind` |
| `model` | string | yes | Concrete model id (e.g. `gpt-5-4`, `claude-opus-4-7`, `gemini-3-1-pro-preview`) |
| `nonce` | string | yes | UUID-seeded, high-entropy nonce; ≥4,096 vendor-tokenized tokens; unique per test |
| `nonce_prefix_tokens` | int | yes | Token count of the leading nonce portion |
| `total_payload_tokens` | int | yes | Total user-content tokens of the cold request |
| `requests` | array | yes | Ordered per-turn entries (see Request Entry below) |
| `verdict` | enum | yes | See Verdicts below |
| `hit_ratio` | number | yes | `cached_tokens / input_tokens` on the warm/post-primitive request |
| `expected_cache_ratio` | number | conditional | Required when test design predicts a hit ratio; used in efficiency delta |
| `efficiency_delta` | number | conditional | `observed - expected`; near zero = behaves as designed |
| `contaminated` | bool | conditional | `true` when first "cold" request reports nonzero cached tokens; result excluded from aggregates |
| `error` | object | conditional | Set on infrastructure or vendor errors; see Failure Records below |
| `actual_wait_seconds` | number | conditional | TTL tests only; recorded when actual wait differs from intended |
| `notes` | string | optional | Free-form operator note |
| `cli_version` | string | optional | Vendor CLI version under test (per DESIGN §5.3 prerequisite pinning) |
| `cli_version_source` | string | optional | Verbatim stdout of the vendor's `--version` command; written by `prefix_warmup` when caching results |
| `cached_at` | ISO 8601 string | optional | When this result was loaded from the warmup cache (only present on `verdict="skipped"` cache loads) |
| `metrics` | object | optional | `prefix_warmup` only. Strict shape — see Metrics block below |

### Metrics block (`prefix_warmup` only)

| Field | Type | Description |
|-------|------|-------------|
| `overhead_per_turn` | int[] | Per-turn `input_tokens - expected_user_content_per_turn` (CLI overhead from system prompt + tool defs) |
| `first_cache_engagement_turn` | int \| null | Smallest turn index where cached_tokens > 0; null if cache never engaged |
| `hit_ratio_per_turn` | float[] | Per-turn `cached_tokens / input_tokens` (0 when input_tokens == 0) |
| `expected_user_content_per_turn` | int[] | Per-turn cumulative count of user-content tokens sent (local count) |

### Request Entry

| Field | Type | Description |
|-------|------|-------------|
| `seq` | int | 0-based turn index |
| `label` | string | `cold` / `warm` / `post_fork` / `post_rewind` / `growth_t<n>` |
| `timestamp` | ISO 8601 string | UTC |
| `input_tokens` | int | From local attribution source (includes CLI overhead) |
| `cached_tokens` | int | OpenAI: `cached_token_count`; Anthropic: `cache_read_input_tokens`; Google: `cached_content_token_count` |
| `cache_creation_tokens` | int | Anthropic only — `cache_creation_input_tokens` |
| `output_tokens` | int | |
| `latency_ms` | int | Wall-clock turn latency |
| `raw_usage` | object | Verbatim usage block from the local source for traceability |

### Verdicts

| Verdict | Meaning |
|---------|---------|
| `cache_hit_confirmed` | Warm/post-primitive request reported cached tokens roughly matching the expected prefix |
| `cache_miss` | Warm/post-primitive request reported zero cached tokens against expectation |
| `byte_identity_preserved` | §4.2 primitive test: fork/rewind preserved the cache |
| `byte_identity_broken` | §4.2 primitive test: fork/rewind invalidated the cache |
| `contaminated` | First "cold" request reported nonzero cached tokens — excluded from aggregates |
| `clean` | Negative-control: both nonces produced no cached tokens (methodology validates) |
| `contaminated_a` / `contaminated_b` | Negative-control: turn A or B contaminated; the methodology may still be sound for the other |
| `methodology_failure` | Negative-control: both nonces shared cache — CLI auto-injected boilerplate creates a shared prefix; CLI-driven §4.1 results are invalid for this vendor |
| `completed` | `prefix_warmup` only — the calibration loop ran to completion without contamination |
| `skipped` | Vendor doesn't support the primitive (rewind on openai/google) OR result loaded from warmup cache |
| `error` | Test failed before producing valid measurements (collector down, tmux failure, parser failure) |

### Failure Records (`error` object)

| Field | Type | Description |
|-------|------|-------------|
| `kind` | enum | `infrastructure` \| `vendor` |
| `message` | string | Human-readable description |
| `vendor_response` | object | For `vendor` kind, the raw vendor error payload |
| `step` | string | Where in the test the failure occurred (e.g. `cold_request`, `tmux_attach`, `parse_local_source`) |

---

## Pricing Schema (§6.2 — `prd/pricing.toml`)

TOML tables keyed `<vendor>.<model>`. Per-1M-token USD rates. Operator updates manually before each forecast run.

| Vendor | Required Keys | Conditional Keys |
|--------|---------------|------------------|
| **OpenAI** (`openai.<model>`) | `input_per_1m`, `cached_input_per_1m`, `output_per_1m` | `extended_context_threshold_tokens`, `extended_context_input_multiplier`, `extended_context_output_multiplier` (when context-gate applies) |
| **Anthropic** (`anthropic.<model>`) | `input_per_1m`, `cache_write_5m_per_1m`, `cache_write_1h_per_1m`, `cache_read_per_1m`, `output_per_1m` | — |
| **Google** (`google.<model>`) | `output_per_1m` | Single-tier: `input_per_1m`, `cached_input_per_1m`. Split-tier: `input_under_200k_per_1m`, `input_over_200k_per_1m`, `cached_input_under_200k_per_1m`, `cached_input_over_200k_per_1m`, `output_under_200k_per_1m`, `output_over_200k_per_1m`. Optional: `cache_storage_per_1m_per_hour` (explicit `cachedContents` only). |

### Context Gate Thresholds

| Model | Gate Threshold | Multiplier (input / output) | Applies to Cached Input |
|-------|---------------:|-----------------------------|-------------------------|
| OpenAI GPT-5.4 | 272K | 2× / 1.5× | Yes |
| Anthropic (all) | None | — | — |
| Google Gemini 3.1 Pro | 200K | 2× / 1.5× | Yes |
| Google Gemini 2.5 Pro | 200K | 2× / 1.5× | Yes |
| Google Gemini 2.5 Flash | None | — | — |

The OpenAI gate is **session-wide**: once cumulative context breaches 272K, the elevated rate applies to the full session, not just the over-threshold tokens.

---

## Cost Forecast Output Schema (§6.3)

| Field | Type | Description |
|-------|------|-------------|
| `forecast_id` | string | `forecast-<timestamp>-<short-id>` |
| `context_probe_config` | object | `{ tiers, questions_per_tier, runs_per_question, vendors }` |
| `per_vendor.<vendor>.strategy_fork_per_question` | object | `{ per_tier_cost[], total_cost, assumptions: { cache_hit_ratio, ttl_sufficient } }` — **uses observed cache ratio from §4.1, not theoretical** |
| `per_vendor.<vendor>.strategy_load_per_question` | object | `{ per_tier_cost[], total_cost, assumptions: { cache_hit_ratio } }` |
| `recommendation` | string | Operator-facing strategy recommendation |
| `total_estimated_cost` | object | `{ fork_per_question, load_per_question }` |

---

## Enums

| Enum | Values |
|------|--------|
| `Vendor` | `openai`, `anthropic`, `google` |
| `TestType` | `cold_warm_pair`, `ttl_mapping`, `prefix_warmup`, `suffix_variation`, `content_growth`, `efficiency_measurement`, `primitive_fork`, `primitive_rewind` |
| `Verdict` | `cache_hit_confirmed`, `cache_miss`, `byte_identity_preserved`, `byte_identity_broken`, `contaminated`, `infra_error`, `vendor_error` |
| `Strategy` | `fork_per_question`, `load_per_question` |

---

## Cache Attribution Field Map

The local source per vendor and the field names that populate the request entry. Field names are tied to the pinned CLI versions in `architecture.md`; verify with `python3 verify-local-sources.py` before relying on them.

| Vendor | Local Source | Tokens-In Field | Cached-Hit Field | Cache-Write Field | Output Field |
|--------|--------------|-----------------|------------------|-------------------|--------------|
| OpenAI / Codex | OTLP→`/tmp/otel-data/codex-logs.jsonl` (logs pipeline) | `input_token_count` | `cached_token_count` | — | `output_token_count` |
| Anthropic / Claude Code | `~/.claude/projects/<slug>/<uuid>.jsonl` last assistant turn `message.usage` | `input_tokens` | `cache_read_input_tokens` | `cache_creation_input_tokens` (with TTL tier) | `output_tokens` |
| Google / Gemini | `~/.gemini/telemetry.log` per-record attributes | `input_token_count` | `cached_content_token_count` | — (implicit caching has no write premium) | `output_token_count` |

---

## Conventions

- **No DB, no migrations.** Result records are append-only files in `results/`. Schema evolution is by version field on the record, not migrations.
- **Nonce uniqueness is a data invariant.** Two test cases sharing a cacheable prefix is a defect — the run must regenerate the nonce and retest.
- **Contaminated records are kept on disk** (with `contaminated: true`) but excluded from aggregate calculations (TTL curves, efficiency ratios, cost forecast inputs). Never silently drop them.
- **Warmup result caching.** Per-vendor, per-model, per-CLI-version warmup measurements may be cached locally. Invalidate when any of those three change. The operator can force a fresh warmup regardless of cache state.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| No relational DB | Flat JSON files in `results/` | Outputs are append-only measurements; vendor/test_type/verdict at top level keeps results human-readable without tooling |
| Local attribution over API | Read from Claude JSONL / Gemini OTel / Codex OTLP | API response bodies are not always exposed by the CLIs; local sources are cost-complete and stable |
| Nonce ≥ 4,096 tokens | Clears the highest documented minimum cacheable prefix across all vendors and models | Single nonce size that works everywhere |
| Per-vendor token verification | Use each vendor's tokenizer (`count_tokens` endpoint or local) | Tokenizer differences across vendors make a fixed bytes-to-tokens ratio unsafe |
| Pricing in TOML, not code | `pricing.toml` operator-editable | Vendor rates change without notice; operator must update before each forecast |
| Observed cache ratio in forecast | Forecast uses §4.1 observed ratio, not theoretical | Vendor reality diverges from documentation; theoretical projections systematically underestimate cost |
