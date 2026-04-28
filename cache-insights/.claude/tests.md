# Testing Strategy

Purpose: Cache Insights *is* a testing system — its purpose is to test vendor cache behavior. This file covers two distinct concerns: (1) the **product tests** the system runs against vendors (cache behavior, primitive validation), and (2) the **engineering tests** that verify the harness itself is correct.

---

## 1. Our Testing Philosophy

**Overall Goal: Produce verifiable measurements that the Context Probe operator can trust to forecast cost and select an execution strategy.**

Two non-negotiables:

1. **Verifiable cold starts.** Every "cold" measurement must be cold. Per-test nonce injection with ≥4,096 tokens is the system's correctness primitive. A cold request that reports nonzero cached tokens is contaminated and excluded from aggregates — never silently treated as valid.
2. **Local-source attribution.** Cache evidence comes from each vendor's local file (Claude JSONL, Gemini OTel log, Codex OTLP→file). API self-reports are not authoritative because the CLIs do not always expose them.

We do **not** chase code coverage. We chase invariant coverage: every cold request is verified cold; every primitive verdict is reproducible; every cost projection traces back to observed (not theoretical) cache ratios.

---

## 2. Types of Tests

### 2.1 Product Tests (the system's payload)

These are the §4.1 and §4.2 tests defined in `prd/DESIGN.prd.md`. They run through the vendor CLIs via tmux against real APIs and produce records under the §6.1 schema.

| Test Type | What It Measures | Source |
|-----------|------------------|--------|
| **Cold/warm pair** | Whether sending the same nonced payload a second time hits cache | DESIGN §4.1 |
| **TTL mapping** | The empirical TTL curve per vendor (30s → 24h ascending, early-terminate on miss) | DESIGN §4.1 |
| **Prefix warmup & meter calibration** | CLI overhead (system prompt + tool definitions + framing) and the turn at which `cached_tokens > 0` | DESIGN §4.1 |
| **Cache prefix stability — suffix variation** | Whether changing the trailing portion invalidates the cached prefix | DESIGN §4.1 |
| **Cache prefix stability — content growth** | Whether appending new content invalidates prior-turn cache | DESIGN §4.1 |
| **Cache efficiency measurement** | Observed vs expected `cached_tokens / input_tokens`; the forecast uses observed | DESIGN §4.1 |
| **Primitive validation — fork** | Whether `codex fork` / `claude --fork-session` / `gemini /resume save+resume` preserves cache | DESIGN §4.2 |
| **Primitive validation — rewind** | Whether `Esc-Esc` rewind preserves cache on each CLI | DESIGN §4.2 |
| **Cost forecast** | Per-vendor, per-strategy dollar estimate using §4.1 observed ratios + `pricing.toml` | DESIGN §4.3 |
| **Cross-vendor comparison** | Normalized table of cache properties across the three vendors | DESIGN §4.4 |

**Required invariants on every product test:**
- Unique nonce per test case (UUID-seeded; ≥4,096 vendor-tokenized tokens).
- First "cold" request reports zero cached tokens, verified via the local source. Nonzero → `contaminated: true` and excluded from aggregates.
- Result written to `results/` per the §6.1 schema with vendor/test_type/verdict at the top level.

### 2.2 Engineering Tests (the harness's correctness)

The harness is the test driver — its bugs become silent measurement errors. Engineering tests cover:

| Layer | What's Tested | Tool |
|-------|---------------|------|
| **Local-source parsers** | Each parser correctly extracts `input_tokens`, `cached_tokens`, `output_tokens` (and Anthropic's `cache_creation_input_tokens` + TTL tier) from the vendor's local file | `pytest` against fixture files captured from real CLI runs |
| **Nonce generator** | Generates a unique nonce per call; tokenizes to ≥4,096 tokens against each vendor's tokenizer | `pytest` with vendor token-counting endpoints (or local tokenizer where applicable) |
| **Pricing math** | Cost forecast applies the right rate for cached vs uncached tokens, applies context-gate multipliers above thresholds, and uses observed (not theoretical) ratios | `pytest` with synthetic result fixtures |
| **Failure handling** | Contaminated, infrastructure, vendor, and TTL-interruption failures each produce the documented error shape and do not abort the run | `pytest` with simulated failures |
| **Result schema** | Every produced record validates against the §6.1 JSON schema | `pytest` + `jsonschema` |
| **Verify-local-sources script** | `python3 verify-local-sources.py` runs without error and prints expected fields per vendor | Smoke test, not unit test |

### 2.3 What We Don't Test

- **Throughput / concurrency.** Out of scope (DESIGN §2.2).
- **Vendor billing reconciliation.** The system measures what vendors *report* as cached locally; it does not verify billing matches the published rates (DESIGN §4.1 efficiency note).
- **End-to-end UI.** There is no UI.

---

## 3. Testing Frameworks & Tools

| Tool | Use |
|------|-----|
| **pytest** | All engineering tests (parsers, math, schema, failure handling) |
| **jsonschema** | Validate result records against the §6.1 schema |
| **tmux** | Drives the vendor CLIs for product tests (also used in tests when verifying tmux orchestration) |
| **Real vendor CLIs** | Codex CLI 0.122.0, Claude Code 2.1.116, Gemini CLI 0.38.2 — pinned versions are part of the test contract |
| **OTel Collector (Docker)** | Required for any Codex test case to land usage in `/tmp/otel-data/codex-logs.jsonl` |

**How to run tests (commands TBD until harness exists):**

```bash
# Engineering tests (local, no vendor calls, no spend)
pytest -q

# Verify local sources are wired up correctly
python3 verify-local-sources.py

# Product tests — these spend money. Always run the cost forecast first.
# (Concrete commands TBD once the harness lands. Expected operator workflows
#  are listed in DESIGN.prd.md §5.)
```

---

## 4. Key Test Scenarios

The scenarios that absolutely must work. Sourced from the DESIGN acceptance criteria (§8) and the open questions (§9).

### Product Scenarios

| # | Scenario | Verdict Source |
|---|----------|----------------|
| 1 | A nonced cold request to each vendor reports zero cached tokens | §4.1 cold/warm pair, cold leg |
| 2 | A second send of the same nonced payload reports cached tokens roughly equal to the prefix size | §4.1 cold/warm pair, warm leg |
| 3 | TTL mapping for each vendor produces an ascending walk that terminates on first miss, recording the last interval that hit | §4.1 TTL mapping |
| 4 | Prefix warmup reveals the per-vendor CLI overhead (delta between expected and reported `input_tokens`) | §4.1 prefix warmup |
| 5 | Suffix variation: changing the trailing portion does NOT invalidate the cached prefix on any vendor | §4.1 prefix stability |
| 6 | Content growth: appending new content does NOT invalidate prior-turn cache on any vendor | §4.1 prefix stability |
| 7 | Fork primitive: `codex fork` / `claude --fork-session` / `gemini /resume save+resume` each preserve cache → `byte_identity_preserved` | §4.2 primitive fork |
| 8 | Rewind primitive: `Esc-Esc` on each CLI preserves the pre-rewound prefix cache | §4.2 primitive rewind |
| 9 | Cost forecast produces fork-per-question and load-per-question totals per vendor using observed ratios from §4.1 | §4.3 |
| 10 | Cross-vendor comparison table is filled with empirically-sourced values for every required column | §4.4 |
| 11 | Sonnet 4.6 minimum cacheable prefix is empirically resolved (1024 vs 2048) | §9 open question |
| 12 | OpenAI 272K surcharge interaction with caching is verified at scale | §9 open question |

### Failure-Handling Scenarios

| # | Scenario | Required Behavior |
|---|----------|-------------------|
| 13 | A "cold" request reports nonzero cached tokens | Result records `contaminated: true`; excluded from aggregates; run continues |
| 14 | The OTel collector is not running when a Codex test starts | Result records `error.kind = "infrastructure"` with descriptive message; run continues |
| 15 | A vendor returns a rate-limit / auth error | Result records `error.kind = "vendor"` with the raw vendor response; run continues |
| 16 | A TTL test sleep is interrupted | Actual elapsed wait is recorded (not the intended wait); flagged when actual differs from intended by >10% |
| 17 | The pricing TOML is missing a key required for the model under test | Forecast errors loudly with the missing key, does not fall back to defaults |
| 18 | A nonce collides across two test cases | Run regenerates the nonce and retries; collision is recorded for traceability |

### Engineering Scenarios

| # | Scenario | Required Behavior |
|---|----------|-------------------|
| 19 | Each parser handles a real captured fixture and extracts every field listed in `data-model.md` "Cache Attribution Field Map" | Unit test with checked-in fixtures |
| 20 | Cost math applies the OpenAI session-wide 272K surcharge once context breaches the gate | Unit test with synthetic forecast inputs |
| 21 | Cost math applies the Google ≤200K / >200K split correctly, including for `cached_input_*` rates | Unit test with synthetic forecast inputs |
| 22 | Anthropic write-tier rates (5m vs 1h) are applied separately to `cache_creation_input_tokens` based on TTL tier | Unit test with synthetic forecast inputs |
| 23 | Result records validate against the JSON schema; missing required fields fail loudly | `jsonschema` validation in CI / pre-commit |

---

## 5. Pre-Run Checklist

Before kicking off any §4.1 / §4.2 product run, verify:

- [ ] `python3 verify-local-sources.py` passes for every vendor under test
- [ ] OTel Collector is running and `/tmp/otel-data/codex-logs.jsonl` is writable (Codex tests only)
- [ ] `prd/pricing.toml` has been re-verified against vendor pricing pages within the last 7 days
- [ ] §4.3 cost forecast was run from prior results to confirm expected spend bound
- [ ] `prd/config.env` is gitignored and the project/workspace filters (`OPENAI_PROJECT_ID`, `ANTHROPIC_WORKSPACE_ID`) are populated
- [ ] Warmup result cache for each (vendor, model, CLI version) tuple is current — re-run warmup if any of the three has changed since the last cached measurement
