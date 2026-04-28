# Cache Insights — Product Requirements

## Document Purpose

This document specifies the capabilities, invariants, and acceptance criteria for a cross-vendor prompt cache measurement system targeting the three major AI coding assistant API providers: OpenAI, Anthropic, and Google. It defines *what* the system must do and *what properties* its behavior must satisfy. It does not prescribe *how* to build any capability.

This system is a prerequisite for the Context Probe (`../context-probe/DESIGN.prd.md`). Its findings determine the execution strategy and cost ceiling for the Context Probe.

### Pinned Tool Versions

| Tool | Version | Binary |
|---|---|---|
| OpenAI Codex CLI | `codex-cli 0.122.0` | `codex` |
| Anthropic Claude Code | `2.1.116` | `claude` |
| Google Gemini CLI | `0.38.2` | `gemini` |
| Python | `3.12.3` | `python3` |
| Node.js | `v22.2.0` | `node` (Gemini CLI runtime) |

### Companion Documents

- `lexicon.prd.md` — vendor reference for CLI commands, API endpoints, auth mechanisms, and per-tool behaviors.
- `research.md` — research findings on per-vendor cache mechanics and methodology.
- `lessons_learned/` — documented assumptions that changed during investigation and how they affected system design.
- `../context-probe/DESIGN.prd.md` — the dependent system that consumes this system's findings.

---

## 1. Background and Motivation

Prompt caching is a server-side optimization offered by all three target providers. When a request shares a common prefix with a recent prior request, the server may reuse cached key-value tensors and bill the cached portion at a discounted rate. Each vendor implements caching differently — matching semantics, cache scope, TTL behavior, discount magnitude, and opt-in requirements vary across providers.

For the Context Probe, caching is the dominant cost variable. If the probe can fork from a loaded state and ask multiple questions at the cached rate, the per-question marginal cost drops significantly. If each question must load fresh, cost scales linearly with question count.

This system answers three questions:

1. **Does the cache work as documented?** — Are each vendor's stated mechanics empirically accurate?
2. **Do CLI primitives preserve cache?** — When the Context Probe forks or rewinds a session, does the subsequent request hit cache?
3. **What's the effective cost model?** — Given empirical cache behavior, what does the Context Probe cost per tier per question per vendor?

These questions must be answered before the Context Probe runs at scale. Cache behavior is vendor-managed infrastructure. Measurements are point-in-time observations — TTL, discount, and cache scope may vary by account tier, server load, or vendor-side changes. The cost forecast (§4.3) treats empirical measurements as the best available estimate, not as a guarantee.

---

## 2. Goals and Non-Goals

### 2.1 Goals

1. **Cost forecasting** — predict the dollar cost of running the Context Probe under different execution strategies (fork-per-question vs load-per-question).
2. **Primitive validation** — determine whether each vendor's fork/resume/rewind CLI primitives preserve the server-side prefix cache.
3. **Cache mechanics characterization** — measure TTL, minimum cacheable prefix size, cache scope, discount magnitude, and cross-invocation behavior per vendor.
4. **Cross-vendor comparison** — produce a normalized table of cache properties for tool-selection decisions.

Every measurement that claims "cold" must be verifiably cold (zero cached tokens on the first request). The system uses per-test nonce injection to guarantee this.

### 2.2 Non-Goals

- Not a load test (no throughput or concurrency measurement).
- Not a billing reconciliation tool (measures what vendors report as cached via local attribution, not literal invoices).
- Does not modify operator CLI configuration, credentials, or session state beyond the one-time telemetry enablement described in §5.3.

---

## 3. Vocabulary

**Provider.** An API vendor whose prompt caching behavior the system measures. Initial set: OpenAI, Anthropic, Google.

**Cache entry.** A server-side stored key-value tensor set associated with a specific byte prefix. Created automatically (OpenAI, Google) or via explicit markers (Anthropic).

**Cache hit / miss.** Whether a request's prefix matches an existing entry and receives the discounted rate.

**Cache attribution field.** The per-response field indicating how many tokens were served from cache:
- OpenAI: `usage.prompt_tokens_details.cached_tokens`
- Anthropic: `usage.cache_read_input_tokens`
- Google: `usageMetadata.cachedContentTokenCount`

**Cost-complete usage block.** The minimum set of per-call fields needed to compute exact dollar cost: total input tokens, cached input tokens (discount rate), uncached input tokens (full rate), and output tokens (full rate). Anthropic adds cache-creation tokens (premium rate with TTL-tier breakdown). Any data source used for cost tracking must expose all fields in this block.

**Nonce.** A unique, high-entropy token sequence injected at the beginning of a synthetic prompt to guarantee cache miss on the first request. All test payloads use a minimum of 4,096 tokens to clear the highest documented minimum cacheable prefix across all vendors and models. Nonce properties:
- Must be unique across all test cases within a run and across runs. A UUID-seeded random generator satisfies this.
- Must produce at least 4,096 tokens when tokenized by the target vendor's model. Since tokenizers differ across vendors, the implementation should verify the token count using each vendor's token-counting mechanism (e.g., the API's `count_tokens` endpoint or a local tokenizer) rather than assuming a fixed bytes-to-tokens ratio.
- Content should be semantically inert — the model's behavior in response to the nonce should not vary in a way that affects token consumption. Random alphanumeric text or repeated dictionary words both satisfy this.
- The nonce value must be recorded in the test result (§6.1 schema) so that contamination can be traced.

**Gate check.** A small, cheap, fast set of API calls whose results determine whether the Context Probe should proceed and under what strategy.

**Primitive.** A CLI-specific operation under test:
- **Fork:** `codex fork` (OpenAI), `claude --fork-session` (Anthropic), `gemini /resume save + /resume resume` (Google)
- **Rewind:** `Esc-Esc` key sequences on all three CLIs

---

## 4. Core Capabilities

All tests are executed through the vendor CLIs (not direct API calls). Cache attribution is read from local files after each turn. The CLIs authenticate via their own credentials; this system does not require separate API keys for testing.

**Model scope:** The system tests against the models defined in `pricing.toml` (§6.2). At minimum, the system must test one model per vendor that matches the Context Probe's intended operating model. The default model per vendor is defined in `config.env` via `DEFAULT_MODEL_CODEX`, `DEFAULT_MODEL_CLAUDE`, and `DEFAULT_MODEL_GEMINI`.

### 4.1 Cache Behavior Tests (CLI-driven, nonced input)

The system drives each vendor's CLI through a series of test cases using nonced input and reads the cache attribution fields from local sources after each turn. "Nonced input" refers to test payloads whose leading bytes include a unique nonce (§3) that guarantees cache isolation. The remainder of the payload may be any content — random text, repeated words, or real corpus material — as long as the nonce makes the overall prefix unique per test case. In practice, nonced input and synthetic input are interchangeable; the nonce is the property that matters for measurement integrity.

**Invariants:**

- Unique nonce per test case. No two test cases share a cacheable prefix unless explicitly intended.
- First request in any "cold" test case must report zero cached tokens. Nonzero = contaminated; exclude from analysis.
- All tests are executed through the CLI via tmux. The system reads cache attribution from local files (Claude JSONL, Gemini OTel, Codex OTel) — not from the API response body.
- The nonce (defined in §3) is delivered as user message content through each CLI's standard prompt input mechanism. See `lexicon.prd.md` §5 for per-vendor prompt delivery methods.
- Minimum user-content payload size: 4,096 tokens per test case.

**Required test types per vendor:**

| Test type | What it measures |
|---|---|
| Cold/warm pair | Send a nonced payload as the first user turn. Send the same user content as a second turn in the same session. The second turn's full request includes conversation history from the first turn; the cache hit is on the shared prefix (system prompt + tools + first-turn content). Measure `cached_tokens` on the second request. |
| TTL mapping | Send nonced payload, exit session, wait N seconds (30s, 1m, 2m, 5m, 10m, 30m, 60m, 4h, 24h), resume session, resend. Walk intervals ascending; stop on first miss. Map per-vendor TTL curve. Uses the same per-vendor session resume mechanism as §4.2; see `lexicon.prd.md` §5 for resume commands per vendor. |
| Prefix warmup and meter calibration | See below. |
| Cache prefix stability | See below. |
| Cache efficiency measurement | See below. |

**Prefix warmup and meter calibration:**

Launch a fresh CLI session per vendor. Send an initial unique payload of ~128 tokens. On each subsequent turn, append a fresh ~128-512 token increment to the cumulative user content. After each turn, read `input_tokens` and `cached_tokens` from the local attribution source. Record:
- The delta between expected user-content tokens and reported `input_tokens` (reveals CLI overhead from system prompt, tool definitions, conversation framing)
- The turn at which `cached_tokens` first exceeds zero (reveals effective cache engagement threshold for this CLI + model combination)
- The `cached_tokens / input_tokens` ratio per turn (reveals cache coverage as context grows)

This test serves as both a cache boundary observation and a meter calibration for the cost forecast. Any persistent divergence between expected and reported token counts must be accounted for in §4.3 cost projections.

**Warmup result caching:** The prefix warmup test produces a per-vendor, per-model CLI overhead measurement that is stable across runs for a given CLI version. The system may cache warmup results locally and reuse them on subsequent runs when the vendor, model, and CLI version match. When any of these change, the system must re-run the warmup test. The operator must be able to force a fresh warmup regardless of cached state.

**Cache prefix stability:** Two tests per vendor using synthetic payloads:
- **Suffix variation:** Verify that changing the trailing portion of a request does not invalidate the cached prefix.
- **Content growth:** Verify that appending new content to a session does not invalidate the cached prefix from prior turns.

Example — suffix variation:
```
Turn 1: send nonced payload (~4096 tokens unique text)
Turn 2: send "say alpha" → read cached_tokens (baseline, expect >0)
Turn 3: fork session
Turn 4: send "say bravo" on fork → read cached_tokens
  Expected: cached_tokens ≈ turn 2 (shared prefix preserved despite different suffix)
  Failure:  cached_tokens = 0 (suffix change invalidated the prefix)
```

Example — content growth:
```
Turn 1: send nonced payload A (~4096 tokens unique text)
Turn 2: read cached_tokens (baseline, may be 0 on first call)
Turn 3: send additional unique payload B (~2048 tokens) in same session
Turn 4: read cached_tokens
  Expected: cached_tokens > 0 (prefix from payload A still cached)
  Failure:  cached_tokens = 0 (content append invalidated the entire prefix)
```

These tests validate that the vendor's cache matches on the longest common prefix rather than invalidating on any suffix change — the property the Context Probe's fork-per-question and incremental-tier-loading strategies depend on.

**Cache efficiency measurement:** For each test case that includes a warm request, the system computes:
- **Expected cache ratio:** the proportion of input tokens the test design predicts should hit cache (e.g., 1.0 for an identical resend, prefix_size / total_size for a suffix-variation test).
- **Observed cache ratio:** `cached_tokens / input_tokens` as reported by the local attribution source.
- **Efficiency delta:** observed minus expected. A delta near zero means the cache behaves as predicted. A negative delta means the cache is less effective than the test design assumed — the system must surface this so the cost forecast can use the observed ratio rather than the theoretical one.

The cost forecast (§4.3) uses the observed cache ratio, not the expected ratio, when projecting costs. Published rates from `pricing.toml` are applied to the observed token split. The system does not verify that vendors bill at the published rate — it measures what the vendor reports as cached and computes savings from that.

**Output:** structured JSON per test case — vendor, test type, nonce, per-request `{input_tokens, cached_tokens, output_tokens}`, expected cache ratio, observed cache ratio, efficiency delta, timestamps, pass/fail verdict.

### 4.2 CLI Primitive Cache Validation (CLI-driven, tmux)

The system drives each vendor's CLI through a fork or rewind operation and determines whether the post-primitive request hits cache.

**Per-call cache attribution sources:**

Each CLI exposes cost-complete usage data locally:

| CLI | Fields | Location | Opt-in |
|---|---|---|---|
| Codex CLI | `input_token_count`, `cached_token_count`, `output_token_count`, `reasoning_token_count`, `tool_token_count` | OTel logs via OTLP to local collector | `[otel.trace_exporter.otlp-http]` in config.toml + local OTel Collector with logs pipeline |
| Claude Code | `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens` + TTL tier, `service_tier`, `inference_geo` | Per-session JSONL at `~/.claude/projects/<slug>/<uuid>.jsonl` | None — always written |
| Gemini CLI | `input_token_count`, `output_token_count`, `cached_content_token_count` | OTel telemetry log at `~/.gemini/telemetry.log` | `telemetry.enabled: true` + `telemetry.target: "local"` in settings.json |

Field names and paths are tied to the pinned CLI versions listed above. The JSON structure of each vendor's local attribution output varies by vendor and CLI version. The `verify-local-sources.py` script reads each vendor's local source and prints the field names, paths, and sample values. The implementation should run this script against the target environment to confirm the expected structure before building parsers.

Codex CLI exports OTel via OTLP but does not write directly to file. A local OTel Collector is required as a prerequisite; see §5.3 for setup.

**Invariants:**

- Unique nonce per test case.
- Zero cached tokens on the first request (pre-primitive baseline), verified via the local source.
- Cache attribution captured on the post-primitive request; hit ratio reported.
- Six test cases: 3 vendors × 2 primitives (fork + rewind). §4.1's prefix stability test (suffix variation) uses fork as a mechanism to test whether the cache survives a suffix change. §4.2 tests whether the fork primitive itself preserves the pre-fork cache entry and reports a byte-identity verdict. The test mechanics overlap; the difference is in what is being measured and reported.

Example — fork test:
```
Turn 1: send nonced payload (~4096 tokens) → read cached_tokens (expect 0, cold baseline)
Turn 2: send "say alpha" → read cached_tokens (expect >0, confirms cache established)
Turn 3: fork session (codex fork / claude --fork-session / gemini /resume save)
Turn 4: send "say bravo" on forked session → read cached_tokens
  Expected: cached_tokens ≈ turn 2 (fork preserved the prefix cache)
  Failure:  cached_tokens = 0 (fork invalidated the cache)
```

Example — rewind test:
```
Turn 1: send nonced payload (~4096 tokens) → read cached_tokens (expect 0, cold baseline)
Turn 2: send "say alpha" → read cached_tokens (expect >0, confirms cache established)
Turn 3: execute rewind (Esc-Esc key sequence, vendor-specific navigation)
         — this undoes turn 2, returning the session to post-turn-1 state
Turn 4: send "say bravo" in rewound session → read cached_tokens
  Expected: cached_tokens ≈ turn 2 (rewind preserved the prefix cache from turn 1)
  Failure:  cached_tokens = 0 (rewind invalidated the cache)
```

Fork creates a new session branch (the original is unchanged). Rewind mutates the current session by removing the last turn. Both should preserve the prefix cache, but the post-primitive session state differs — the implementation must handle each accordingly. See `lexicon.prd.md` §5 for per-vendor fork and rewind commands.

**Output:** structured JSON per test case — vendor, primitive name, nonce, pre/post `{input_tokens, cached_tokens}`, hit ratio, verdict (`byte_identity_preserved` or `byte_identity_broken`).

### 4.3 Cost Forecasting

Takes empirical measurements from §4.1 and §4.2, combines with per-vendor pricing, and produces a cost estimate for the Context Probe.

**Invariants:**

- Pricing table stored in `pricing.toml`, operator-updatable.
- Computes cost under at least two strategies:
  - **Fork-per-question:** 1 × full-load + N × cached-question per tier.
  - **Load-per-question:** N × full-load + N × uncached-question per tier.
- Reports per-tier, per-question, per-vendor cost plus aggregate across the full Context Probe matrix.
- Reports the empirical TTL per vendor (from §4.1 TTL mapping results) alongside the per-strategy cost estimates. The Context Probe operator uses the TTL to assess whether the fork-per-question strategy is viable for their expected run pacing.
- Applies context gate multipliers (§6.2) when cumulative tier context exceeds the model's gate threshold.

The cost forecast uses observed `input_tokens` from §4.1 test results, which include CLI overhead (system prompt, tool definitions, conversation framing). Token counts derived from user-content size alone underestimate actual cost. The prefix warmup test (§4.1) quantifies this overhead per vendor.

**Output:** cost forecast in JSON and/or Markdown, per-cell breakdowns, aggregate per strategy per vendor.

### 4.4 Cross-Vendor Comparison

Produces a normalized table of cache properties.

**Required columns:**
- Cache mechanism type (automatic / explicit markers / both)
- Cache scope (org / workspace / project)
- Minimum cacheable prefix (tokens)
- Empirically measured TTL
- Documented TTL (for comparison)
- Cache discount (% off standard input rate)
- Cache attribution field name and location in API response body
- Local per-call attribution source and field names
- Whether fork preserves cache (empirical yes/no)
- Whether rewind preserves cache (empirical yes/no)
- Whether a "force cold call" mechanism exists

**Output:** Markdown table for inclusion in `research.md` and the lexicon.

---

## 5. Architecture

```
cache-insights/
├── <cache-test>              # §4.1 + §4.2 — CLI-driven, tmux, per-vendor drivers
├── <cost-forecast>           # §4.3 — reads test results, applies pricing
├── pricing.toml              # per-vendor per-model pricing table
├── config.env                # model defaults, vendor config
├── research.md               # findings + methodology
├── lessons_learned/          # documented assumption changes
└── results/                  # structured output
```

Component names above are illustrative. The implementation may use any file names, directory structure, or language that satisfies the capabilities described in §4.

**Component dependencies:** §4.3 (cost forecast) and §4.4 (cross-vendor comparison) consume results from §4.1 and §4.2. §4.1 (cache behavior tests) and §4.2 (primitive validation) have no dependencies on each other and share the same CLI-driven testing infrastructure. §4.1 alone produces sufficient data for the Context Probe go/no-go decision.

### 5.1 Cache test component

Implements §4.1 (cache behavior tests) and §4.2 (primitive validation). CLI-driven via tmux. Synthetic input with per-test nonces. Reads local per-call attribution (Claude JSONL, Gemini OTel, Codex OTel via collector).

**Dependencies:** Python 3.11+, tmux, the three CLI tools installed and authenticated, local OTel Collector for Codex.

**Estimated cost:** ~$3-5 per full run across all vendors and test types.
**Estimated wall-clock:** ~45 minutes for short-interval tests. Up to ~28 hours if the 24h TTL interval is included (early termination on first miss reduces this in practice).

### 5.2 Cost forecast component

Implements §4.3. Reads results from the cache test component, applies `pricing.toml`. No API calls, zero cost.

**Dependencies:** Python 3.11+, results from §5.1, `pricing.toml`.

### Operator workflows

The system must support the following operator workflows:
- Run all §4.1 test types for a single vendor.
- Run a single §4.1 test type across all vendors.
- Run the full §4.1 + §4.2 suite across all vendors.
- Run §4.2 primitive validation only (fork, rewind, or both) for a single vendor.
- Run §4.3 cost forecast from existing results without re-running tests.
- All test output writes to the `results/` directory with structured JSON per the §6.1 schema.
- Results are human-readable without additional tooling — the §6.1 JSON schema places vendor, test type, and verdict at the top level of each result file.

### 5.3 Per-Vendor Prerequisites

One-time setup required before running tests. Each CLI must be installed, authenticated, and configured to emit local per-call attribution data. The CLIs handle their own API authentication — this system does not require separate API keys.

#### OpenAI / Codex CLI

Codex CLI does not write per-call usage to a local file by default. Two configuration changes are required:

1. Enable OTel export in `~/.codex/config.toml`:
   ```toml
   [otel.trace_exporter.otlp-http]
   endpoint = "http://localhost:4318/v1/traces"
   protocol = "json"
   ```

2. Run a local OTel Collector that receives OTLP and writes to a file. Minimal Docker setup:
   ```yaml
   # otel-collector-config.yaml
   receivers:
     otlp:
       protocols:
         http:
           endpoint: "0.0.0.0:4318"
   exporters:
     file/logs:
       path: /data/codex-logs.jsonl
   service:
     pipelines:
       logs:
         receivers: [otlp]
         exporters: [file/logs]
   ```
   ```bash
   mkdir -p /tmp/otel-data && touch /tmp/otel-data/codex-logs.jsonl && chmod 666 /tmp/otel-data/codex-logs.jsonl
   docker run --rm \
     -v $(pwd)/otel-collector-config.yaml:/etc/otelcol/config.yaml \
     -v /tmp/otel-data:/data \
     -p 4318:4318 \
     otel/opentelemetry-collector
   ```

   The collector must be running before any §4.2 Codex test case executes. Token usage fields (`input_token_count`, `cached_token_count`, `output_token_count`) appear in the logs pipeline output, not the traces pipeline.

#### Anthropic / Claude Code

No additional setup. Claude Code writes per-turn usage data (including all cache attribution fields) to its session JSONL at `~/.claude/projects/<slug>/<uuid>.jsonl` by default. The implementation reads the last assistant turn's `message.usage` block after each operation.

#### Google / Gemini CLI

Gemini CLI does not write per-call telemetry by default. Add the following to `~/.gemini/settings.json`:

```json
{
  "telemetry": {
    "enabled": true,
    "target": "local"
  }
}
```

This causes Gemini CLI to write OTel JSON records to `~/.gemini/telemetry.log` on every model response. Token usage fields (`input_token_count`, `cached_content_token_count`, `output_token_count`) appear as attributes on each record. Merge this with any existing settings.json content — the telemetry block is additive.

---

## 6. Data Model

### 6.1 Per-test result schema

```json
{
  "test_id": "openai-cold-warm-20260409-...",
  "vendor": "openai",
  "test_type": "cold_warm_pair",
  "model": "gpt-5.4",
  "nonce": "8a3f2c19-4b0d-9e7a-...",
  "nonce_prefix_tokens": 128,
  "total_payload_tokens": 5120,
  "requests": [
    {
      "seq": 0,
      "label": "cold",
      "timestamp": "2026-04-09T14:00:00Z",
      "input_tokens": 5120,
      "cached_tokens": 0,
      "output_tokens": 5,
      "latency_ms": 1230,
      "raw_usage": {}
    },
    {
      "seq": 1,
      "label": "warm",
      "timestamp": "2026-04-09T14:00:02Z",
      "input_tokens": 5120,
      "cached_tokens": 4992,
      "output_tokens": 5,
      "latency_ms": 890,
      "raw_usage": {}
    }
  ],
  "verdict": "cache_hit_confirmed",
  "hit_ratio": 0.975,
  "notes": ""
}
```

### 6.2 Pricing and context gates

Pricing as of April 20, 2026. Sources: developers.openai.com/api/docs/pricing, platform.claude.com/docs/en/about-claude/pricing, ai.google.dev/gemini-api/docs/pricing. Rates change without notice — the operator is responsible for verifying `pricing.toml` before each cost forecast.

**Per 1M tokens, USD:**

| Model | Input | Cache Write | Cache Read | Output | Notes |
|---|---:|---:|---:|---:|---|
| OpenAI GPT-5.4 | $2.50 | — (automatic) | $0.25 (90% off) | $15.00 | >272K surcharge below |
| Anthropic Opus 4.7 | $5.00 | $6.25 (5m) / $10.00 (1h) | $0.50 (90% off) | $25.00 | New tokenizer ~35% more tokens vs 4.6 |
| Anthropic Opus 4.6 | $5.00 | $6.25 (5m) / $10.00 (1h) | $0.50 (90% off) | $25.00 | |
| Anthropic Sonnet 4.6 | $3.00 | $3.75 (5m) / $6.00 (1h) | $0.30 (90% off) | $15.00 | |
| Anthropic Haiku 4.5 | $1.00 | $1.25 (5m) / $2.00 (1h) | $0.10 (90% off) | $5.00 | 200K context |
| Google Gemini 3.1 Pro (preview) | $2.00 / $4.00 | — (implicit) | $0.20 / $0.40 | $12.00 / $18.00 | Split at 200K |
| Google Gemini 2.5 Pro (GA) | $1.25 / $2.50 | — (implicit) | $0.125 / $0.25 | $10.00 / $15.00 | Split at 200K |
| Google Gemini 2.5 Flash | $0.30 | — (implicit) | $0.03 | $2.50 | |

**Context gate thresholds:**

| Model | Max context | Gate threshold | Multiplier above gate | Applies to cached input? |
|---|---:|---:|---|---|
| OpenAI GPT-5.4 | 1,050,000 | 272K | 2× input, 1.5× output | Yes |
| Anthropic (all models) | 200K–1M | None | — | — |
| Google Gemini 3.1 Pro | 1,048,576 | 200K | 2× input, 1.5× output | Yes |
| Google Gemini 2.5 Pro | 1,048,576 | 200K | 2× input, 1.5× output | Yes |
| Google Gemini 2.5 Flash | 1,048,576 | None | — | — |

The cost forecast (§4.3) applies the above-gate multiplier to any tier whose cumulative context exceeds the model's threshold. The OpenAI gate is session-wide: once breached, the elevated rate applies to the full session.

**Pricing asymmetries:**
- **OpenAI** — no cache-write premium; 272K surcharge multiplies all rates including cached input.
- **Anthropic** — write premium (1.25× for 5-min, 2× for 1-hr) at creation; cheapest reads (0.1× base); no context-gate surcharge. Break-even: 1 read for 5-min cache, 2 reads for 1-hr.
- **Google** — no write premium for implicit caching; ≤200K / >200K split doubles rates; explicit `cachedContents` incurs storage fees ($1.00–$4.50/MTok/hr).

Per-vendor pricing is maintained in `pricing.toml`. The schema uses TOML tables keyed by `<vendor>.<model>` with per-1M-token rates for input, cached input (read and/or write tiers), output, and any context-gate multipliers or storage fees. See `pricing.toml` for current rates and source URLs.

### 6.3 Cost forecast output schema

```json
{
  "forecast_id": "forecast-20260409-...",
  "context_probe_config": {
    "tiers": 8,
    "questions_per_tier": 5,
    "runs_per_question": 5,
    "vendors": ["openai", "anthropic", "google"]
  },
  "per_vendor": {
    "openai": {
      "strategy_fork_per_question": {
        "per_tier_cost": [],
        "total_cost": 0,
        "assumptions": {
          "cache_hit_ratio": 0.0,
          "ttl_sufficient": false
        }
      },
      "strategy_load_per_question": {
        "per_tier_cost": [],
        "total_cost": 0,
        "assumptions": {
          "cache_hit_ratio": 0.0
        }
      }
    }
  },
  "recommendation": "",
  "total_estimated_cost": {
    "fork_per_question": 0,
    "load_per_question": 0
  }
}
```

---

## 7. Vendor-Specific Notes

Per-vendor cache mechanics that the implementation must account for. Descriptive, not prescriptive. Items marked "to be verified" are expected behaviors from vendor documentation that the §4.1 test must confirm empirically.

### 7.1 OpenAI

- Cache is automatic, org-scoped, exact byte-prefix match, minimum 1024 tokens.
- TTL: documented as 5-60 min in-memory, refreshed on hit. Extended 24h via `prompt_cache_retention` parameter (not exposed by Codex CLI). **TTL curve to be verified by §4.1.**
- `prompt_cache_key` is a routing hint, not a namespace isolator. Cannot force cold calls.
- Cache attribution: `usage.prompt_tokens_details.cached_tokens`.
- Cache discount: $2.50 → $0.25 (90% off) per published pricing. **To be verified by §4.1 discount test.**
- Codex CLI uses Responses API, sets `prompt_cache_key = conversation_id`.
- Local per-call attribution: OTel logs via OTLP collector — `input_token_count`, `cached_token_count`, `output_token_count`. Requires `[otel.trace_exporter.otlp-http]` in config.toml + local OTel Collector with logs pipeline.
- Only way to force cold: mutate the first 1024 tokens.

### 7.2 Anthropic

- Cache is explicit via `cache_control: {type: "ephemeral"}` markers. Claude Code sets these automatically on tools, system prompt, and last content block of each user/assistant message.
- Cache scope: workspace on the 1P API. Bedrock/Vertex remain org-scoped.
- TTL: 5 min default, 1 hr extended (`ttl: "1h"`), refreshed on hit at no cost. **TTL curve to be verified by §4.1.**
- Minimum cacheable prefix: 4096 tokens (Opus 4.6/4.7, Haiku 4.5), 1024 tokens (Sonnet 4.6). **Sonnet boundary to be verified — community reports suggest 2048 in practice.**
- Max 4 explicit breakpoints per request.
- Cache attribution: `usage.cache_read_input_tokens` (hit), `usage.cache_creation_input_tokens` (write), `usage.input_tokens` (uncached). Total = sum of all three.
- Local per-call attribution: session JSONL at `~/.claude/projects/<slug>/<uuid>.jsonl` — full cost-complete usage block including TTL tier breakdown. Always written, no opt-in.
- Only way to force cold: mutate prefix, switch workspace, switch model, or wait past TTL.

### 7.3 Google

- Two caching mechanisms: implicit (automatic, default-on for Gemini 2.5+/3.x, project-scoped) and explicit (`cachedContents` resource, opt-in). Gemini CLI uses implicit only.
- Implicit TTL: "cleared in 24 hours or less" per vendor docs (no SLA). **TTL curve to be verified by §4.1.**
- Minimum cacheable prefix: 1024 tokens (Flash), 4096 tokens (Pro). **Exact boundary to be verified — docs differ between AI Studio and Vertex.**
- Cache attribution: `usageMetadata.cachedContentTokenCount` — reports both implicit and explicit hits, no sub-breakdown.
- Local per-call attribution: OTel telemetry log at `~/.gemini/telemetry.log` — `input_token_count`, `output_token_count`, `cached_content_token_count`. Requires `telemetry.enabled: true` + `telemetry.target: "local"` in settings.json.
- AI Studio: no documented opt-out for implicit caching. Vertex: project-level `cacheConfig.disableCache=true` (global, propagation delay not SLA'd).
- Only way to force cold on AI Studio: mutate prefix or rotate to fresh project.

---

## 8. Acceptance Criteria

**§4.1 output properties:** Structured JSON results (per §6.1 schema) for cold/warm, TTL, prefix warmup, prefix stability, and efficiency measurement tests across all three vendors. Every cold test case's first request shows zero cached tokens. TTL results include the last interval that produced a cache hit per vendor.

**§4.2 output properties:** Structured JSON results (per §6.1 schema) for six primitive test cases (3 vendors × 2 primitives). Each includes a pre-primitive and post-primitive cache attribution reading, a hit ratio, and a verdict.

**§4.3 output properties:** A cost forecast (per §6.3 schema) covering both fork-per-question and load-per-question strategies, with per-tier per-vendor breakdowns using observed cache ratios from §4.1 results and published rates from `pricing.toml`.

**§4.4 output properties:** A cross-vendor comparison table with empirically sourced values for every required column (§4.4 column list).

**System-level:** The outputs above, taken together, provide sufficient information for the Context Probe operator to determine a cost ceiling and select an execution strategy.

**Failure handling properties:**

- **Contaminated test case** (first "cold" request reports nonzero cached tokens): the result must include a `contaminated: true` flag and must be excluded from aggregate calculations (TTL curves, efficiency ratios, cost forecast inputs). The system must not silently treat a contaminated result as valid.
- **Infrastructure failure** (OTel collector not running, tmux session fails to launch, CLI crashes mid-test): the result must include an `error` field with a description. The system must not produce partial results that could be mistaken for valid measurements.
- **Vendor error** (API returns an error, rate limit hit, authentication failure): the result must include the vendor's error response. The system must distinguish vendor errors from infrastructure errors in the output.
- **TTL test interruption** (sleep interrupted by signal or system event): the result must record the actual elapsed wait time, not the intended wait time. A TTL test case whose actual wait differs from intended by more than 10% should be flagged.

In all failure cases, the system continues to the next test case rather than aborting the run. Each failure is recorded independently in the result for that test case. The operator may rerun individual failed test cases without repeating the full suite.

---

## 9. Open Questions

Items that require empirical measurement by this system before the design is fully specified. Each will be closed by §4.1 or §4.2 test results.

1. **Per-vendor TTL curve.** Documented TTLs vary (OpenAI: 5-60 min, Anthropic: 5 min / 1 hr, Google: "≤24 hours"). The §4.1 TTL mapping test walks ascending intervals with early termination on first miss to map each vendor's empirical curve.

2. **Sonnet 4.6 minimum cacheable prefix.** Docs state 1024 tokens; community reports suggest 2048. The §4.1 prefix boundary test will resolve this.

3. **OpenAI 272K surcharge interaction with caching.** The surcharge applies to cached input per the pricing page. The §4.1 discount test at the Context Probe's operating scale (higher tiers exceed 272K) should confirm the effective rate.

4. **Google Vertex `cacheConfig.disableCache` propagation delay.** Not SLA'd. Relevant only if the implementation chooses the Vertex disable path over nonce injection for cold calls. Nonce injection is the expected approach.
