# Architecture Overview

Purpose: High-level system context for quick orientation. Answers: "What is this? How does it fit together? How do I run it?"

> This is the first file a new session should read. Detailed context lives in `data-model.md` (result/pricing schemas), `security.md` (secrets), and `tests.md` (verification strategy).

---

## What We're Building

- **Project Name:** Cache Insights
- **One-Sentence Summary:** A cross-vendor prompt-cache measurement system that drives the OpenAI Codex, Anthropic Claude Code, and Google Gemini CLIs to characterize cache behavior and forecast the cost of running the downstream Context Probe.
- **Programming Languages:**
  - **Backend:** Python 3.12.3 (test harness, cost forecaster, parsers)
  - **Frontend:** None — CLI-only tool
- **Main Frameworks/Tools:**
  - **Driver:** tmux (interactive CLI orchestration; the three vendor CLIs have no batch/stdin mode)
  - **Vendor CLIs under test:** Codex CLI 0.122.0, Claude Code 2.1.116, Gemini CLI 0.38.2
  - **Telemetry sink:** OpenTelemetry Collector (local, Docker) for Codex OTLP→file
  - **Pricing/config:** TOML + bash-sourced env files
  - **Database:** None — outputs are JSON result files in `results/`
  - **Auth:** None (this tool); each vendor CLI authenticates with its own credentials

---

## Product Guidance

### Vision

Cache Insights answers, before the downstream Context Probe spends real money: *does each vendor's prompt cache work as documented, do the CLI fork/rewind primitives preserve it, and what is the dollar cost of the Context Probe under each execution strategy?* Cache behavior is the dominant cost variable for the Context Probe — empirically measuring it determines whether questions can fork from a cached load (cheap) or must each re-load (expensive).

### Product Principles

1. **Verifiable cold starts.** Every "cold" measurement uses a per-test nonce of ≥4,096 tokens. A cold request that reports nonzero cached tokens is contaminated and must be excluded — never silently treated as valid.
2. **Local attribution over API self-report.** Cache attribution is read from each vendor's local source (Claude JSONL, Gemini OTel log, Codex OTLP via collector), not from API response bodies the CLI may not expose.
3. **Empirical over documented.** Vendor docs disagree with each other and with reality (TTLs, minimum prefix sizes, discount magnitudes). The system reports what it observed; the cost forecast uses observed cache ratios, not theoretical ones.
4. **Forecast, not invoice.** Measurements are point-in-time observations of vendor-managed infrastructure. Cost outputs are the best available estimate, not a billing guarantee.
5. **Continue-on-failure.** A single contaminated, errored, or timed-out test case never aborts the run — each failure is recorded in its own result and the next case proceeds.

### Explicit Exclusions

| Excluded Feature | Rationale | Status |
|-----------------|-----------|--------|
| Throughput / concurrency load testing | Goal is cache characterization, not capacity planning | Permanent |
| Billing reconciliation against vendor invoices | Measures what vendors *report* as cached locally; does not verify they bill at published rates | Permanent |
| Modifying operator CLI config beyond the one-time §5.3 telemetry enablement | Avoid surprising the operator with credential or session-state changes | Permanent |
| Direct-API testing path (bypassing the CLIs) | The Context Probe runs through CLIs, so cache behavior must be measured through the same surface | Permanent |
| Vertex `cacheConfig.disableCache` for cold calls | Nonce injection is the chosen cold-call mechanism; Vertex disable propagation is not SLA'd | Deferred |

### Target Personas

| Persona | Description | Priority |
|---------|-------------|----------|
| Context Probe operator | Uses this system's outputs (TTL curves, primitive verdicts, cost forecast) to choose a probe execution strategy and authorize spend | Primary |
| Cache-mechanics researcher | Reads `research.md` and the cross-vendor comparison table for grounded vendor comparisons | Secondary |

---

## Technology Decisions

Before adding a new library, check this table — the problem may already be solved.

| Category | Component | Version | Rationale |
|----------|-----------|---------|-----------|
| **Language** | Python | 3.12.3 | Test harness, parsers, cost math; matches the sibling `context-probe` project |
| **CLI driver** | tmux | system | Vendor CLIs are interactive-only; no stdin/batch mode |
| **Telemetry sink** | OpenTelemetry Collector | latest (Docker) | Codex CLI exports OTLP only — needs a local receiver to land usage in a file |
| **Vendor CLI (OpenAI)** | Codex CLI | 0.122.0 (`codex`) | Pinned version under test |
| **Vendor CLI (Anthropic)** | Claude Code | 2.1.116 (`claude`) | Pinned version under test |
| **Vendor CLI (Google)** | Gemini CLI | 0.38.2 (`gemini`) | Pinned version under test |
| **Runtime (Gemini)** | Node.js | 22.2.0 | Required by Gemini CLI |
| **Pricing config** | TOML | — | `pricing.toml` keyed `<vendor>.<model>`; operator-updatable |
| **Result format** | JSON | — | Schema in §6.1 of `prd/DESIGN.prd.md`; vendor/test_type/verdict at top level for human-readability |
| **Schema validation** | jsonschema | >=4.10 (Python) | `cache_insights/validate.py` validates results against `cache_insights/schemas/result.schema.json` (draft 2020-12) |
| **Database** | None | — | Results are flat JSON files; no persistence layer needed |

> **Update strategy:** CLI versions and pricing are pinned. Re-verify `pricing.toml` against vendor docs before each cost-forecast run; rates change without notice. CLI version bumps invalidate cached prefix-warmup results — re-run warmup when the vendor, model, or CLI version changes.

---

## How to Run

### Prerequisites

- Python 3.12.3, tmux, Docker (for the OTel collector), Node.js 22.2.0 (Gemini CLI runtime)
- Codex CLI 0.122.0, Claude Code 2.1.116, Gemini CLI 0.38.2 — installed and authenticated against their own accounts
- One-time per-vendor telemetry setup per `prd/DESIGN.prd.md` §5.3:
  - **Codex:** add `[otel.trace_exporter.otlp-http]` block to `~/.codex/config.toml` and run a local OTel Collector exporting to `/data/codex-logs.jsonl`
  - **Claude Code:** none — JSONL at `~/.claude/projects/<slug>/<uuid>.jsonl` is always written
  - **Gemini:** add `telemetry: { enabled: true, target: "local" }` to `~/.gemini/settings.json`

### Local Development

```bash
# 1. Verify local attribution sources are wired up per vendor
python3 verify-local-sources.py

# 2. Start the OTel collector for Codex (in a separate terminal)
mkdir -p /tmp/otel-data && touch /tmp/otel-data/codex-logs.jsonl && chmod 666 /tmp/otel-data/codex-logs.jsonl
docker run --rm \
  -v $(pwd)/otel-collector-config.yaml:/etc/otelcol/config.yaml \
  -v /tmp/otel-data:/data \
  -p 4318:4318 \
  otel/opentelemetry-collector

# 3. Run the cache test suite (commands TBD — implementation pending)
# Expected operator workflows (see DESIGN.prd.md §5):
#   - Run all §4.1 tests for one vendor
#   - Run a single §4.1 test type across all vendors
#   - Run full §4.1 + §4.2 suite across all vendors
#   - Run §4.2 primitive validation (fork / rewind) for one vendor
#   - Run §4.3 cost forecast from existing results without re-testing
```

- **Results land in:** `results/` (structured JSON per the §6.1 schema)
- **No HTTP services exposed.** The only listening port is the OTel Collector on `localhost:4318`.

### Environment Health Checks

Used by `/leroy` and `/gogogo` to verify the dev environment is ready.

| Service | Check Command | Expected |
|---------|--------------|----------|
| Python | `python3 --version` | `Python 3.12.3` |
| tmux | `tmux -V` | `tmux 3.x` |
| Codex CLI | `codex --version` | `codex-cli 0.122.0` |
| Claude Code | `claude --version` | `2.1.116` |
| Gemini CLI | `gemini --version` | `0.38.2` |
| Node.js | `node --version` | `v22.2.0` |
| OTel collector | `curl -sf http://localhost:4318/v1/traces -X POST -H 'Content-Type: application/json' -d '{}' >/dev/null && echo "running"` | `running` |
| Codex OTel config | `grep -q 'otlp-http' ~/.codex/config.toml && echo "configured"` | `configured` |
| Gemini telemetry | `jq -e '.telemetry.enabled == true' ~/.gemini/settings.json >/dev/null && echo "enabled"` | `enabled` |
| Claude JSONL dir | `test -d ~/.claude/projects && echo "exists"` | `exists` |
| Pricing table | `test -f prd/pricing.toml && echo "exists"` | `exists` |

---

## System Architecture

```
                  ┌──────────────────────────────┐
                  │  Operator (CLI invocation)   │
                  └──────────────┬───────────────┘
                                 │
                  ┌──────────────▼──────────────┐
                  │  Cache test component (§5.1)│
                  │   - tmux orchestrator        │
                  │   - per-vendor CLI driver    │
                  │   - nonce generator          │
                  │   - local-source parser      │
                  └────┬──────────┬──────────┬───┘
                       │          │          │
            ┌──────────▼─┐  ┌─────▼─────┐  ┌─▼──────────┐
            │  codex CLI │  │ claude CLI│  │ gemini CLI │
            │  (OpenAI)  │  │(Anthropic)│  │  (Google)  │
            └──────┬─────┘  └─────┬─────┘  └─────┬──────┘
                   │              │              │
        ┌──────────▼─────┐  ┌─────▼──────┐  ┌────▼───────────┐
        │ OTel Collector │  │ session    │  │ ~/.gemini/     │
        │ → codex-logs   │  │ JSONL      │  │ telemetry.log  │
        │   .jsonl       │  │            │  │                │
        └──────┬─────────┘  └─────┬──────┘  └────┬───────────┘
               └──────────────┬───┴──────────────┘
                              │
                     ┌────────▼────────┐
                     │  results/*.json │
                     │  (§6.1 schema)  │
                     └────────┬────────┘
                              │
                  ┌───────────▼────────────┐
                  │ Cost forecast (§5.2)   │
                  │  + pricing.toml        │
                  └───────────┬────────────┘
                              │
                  ┌───────────▼────────────┐
                  │ forecast.json/.md      │
                  │ cross-vendor compare   │
                  └────────────────────────┘
```

---

## Directory Structure

```
cache-insights/
├── prd/
│   ├── DESIGN.prd.md            # Product requirements (source of truth)
│   ├── lexicon.prd.md           # Per-vendor CLI/API reference
│   ├── research.md              # Research findings + methodology
│   ├── pricing.toml             # Per-vendor per-model pricing (operator-updatable)
│   ├── config.env               # Model defaults, vendor config, secrets
│   ├── otel-collector-config.yaml
│   └── lessons_learned/         # Domain/product lessons (vendor APIs, cache mechanics)
├── cache_insights/              # Python package (Phase 1 building blocks)
│   ├── _config.py               # config.env loader (lru_cached)
│   ├── validate.py              # jsonschema wrapper for §6.1 result records
│   ├── nonce.py                 # Per-test nonce generator (≥4096 tokens, deterministic)
│   ├── tokenizers.py            # Per-vendor count_tokens (OpenAI/Anthropic/Google APIs)
│   ├── parsers/                 # Local-source attribution parsers
│   │   ├── _io.py               # iter_pretty_json_records + iter_jsonl_records helpers
│   │   ├── claude.py            # ~/.claude/projects/<slug>/<uuid>.jsonl
│   │   ├── codex.py             # /tmp/otel-data/codex-logs.jsonl (OTLP envelope)
│   │   └── gemini.py            # ~/.gemini/telemetry.log (pretty-printed JSON)
│   ├── driver/                  # tmux-based CLI orchestration
│   │   ├── dispatch.py          # VENDOR_LAUNCH dict + LaunchSpec
│   │   └── tmux.py              # TmuxSession + driver() context manager
│   └── schemas/
│       └── result.schema.json   # §6.1 per-test result schema (draft 2020-12)
├── tests/                       # pytest test suite
│   └── fixtures/                # Sample records for parser + validator tests
├── verify-local-sources.py      # Confirms each vendor's local attribution wiring
├── requirements.txt             # Python deps (jsonschema)
├── results/                     # Structured JSON outputs (gitignored)
├── README.md
└── .claude/                     # Claude Code context
    ├── architecture.md          # This file
    ├── data-model.md            # Result + pricing schemas
    ├── security.md              # Secrets, sensitivity, vendor auth
    ├── tests.md                 # Verification strategy
    └── lessons_learned/         # Process/meta lessons (how to work on the project)
```

---

## Deployment

- **Hosting:** Local-only operator workstation. No deployed service.
- **CI/CD:** None — the system is invoked manually by the Context Probe operator.
- **Environments:** Local only.
- **Secrets:** Stored in `prd/config.env` (gitignored). See `security.md` for the credentials inventory and rotation rules.

---

## Related Context Files

For deeper detail, see:
- **`data-model.md`** — Per-test result schema (§6.1), pricing schema (§6.2), cost-forecast schema (§6.3)
- **`security.md`** — Vendor auth modes, admin-API keys, secrets handling
- **`tests.md`** — Cache-behavior tests, primitive validation, contamination handling
- **`prd/DESIGN.prd.md`** — Authoritative product requirements
- **`prd/lexicon.prd.md`** — Per-vendor CLI command and API reference
