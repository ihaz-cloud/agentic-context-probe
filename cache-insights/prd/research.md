# Cache Verification Methodology — Research & Pivot

**Date:** 2026-04-08
**Status:** The framework's existing cache scenarios measure server-side prefix-cache survival, not the framework primitives we claim to test. Pivot required.
**Sources:** Three parallel deep-research subagents (one per provider) plus empirical validation against the framework's own test outputs.

---

## Executive summary

The framework's "cold baseline" scenario (`A`) is contaminated by inter-run cache pollution. A single rep of `A` against Codex shows **73% cache hit** on what should be uncontaminated input — meaning the byte-identical `TIER_1_PROMPT` fixture has been resident in OpenAI's server-side prefix cache for hours from prior runs, and every subsequent "cold" measurement is reading those bytes instead of paying full input price.

The deep research confirms this is **expected behavior across all three vendors**, not a framework bug:

- **OpenAI** (Codex CLI / GPT-5.4): cache is org-scoped, exact-prefix matched, 5–60 min in-memory TTL refreshed on every hit, with no documented opt-out. The `prompt_cache_key` parameter is a routing hint, **not** a namespace isolator — Codex CLI sets it per `conversation_id` and that still does not prevent cross-conversation cache reuse on identical prefixes.
- **Anthropic** (Claude Code / Opus 4.6): cache is workspace-scoped (since Feb 5 2026), 5 min ephemeral TTL refreshed on hit (1 h extended TTL available), explicit `cache_control` markers required but **Claude Code sets them automatically** on tools, system prompt, and the last block of every user/assistant message. No documented `no-cache` flag.
- **Google** (Gemini CLI / Gemini 3.x): two simultaneous mechanisms — implicit caching (default-on, project-scoped, ≤24 h TTL, no opt-out at AI Studio, only a project-level kill switch on Vertex) and explicit `cachedContents` (the framework's CLI does not use this). The `cached_content_token_count` field reports both implicit and explicit hits in the same number.

**The methodological pivot:** every "cold" run must mutate the prompt prefix by injecting a per-run unique nonce before the first byte the server might match against. Without this, all three vendors will hit cache on bytes left over from prior runs, and the framework's measurements will reflect cache TTL behavior instead of CLI primitive behavior.

This document records the per-vendor research, the exact mechanism each cache uses, the framework's bug, and the proposed redesign.

---

## 1. Empirical evidence — the framework's own data

Verified against `test-output/cache-codex-*/results.json` files in the repo:

| Run ID | Scenario | Reps | Input tokens | Cached tokens | **Hit %** |
|---|---|---|---:|---:|---:|
| `cache-codex-20260407-152003` | A (cold baseline) | 5 | 1,789,341 | 1,151,872 | **64.4%** |
| `cache-codex-20260407-152003` | B (in-process fork) | 5 | 1,423,693 | 1,079,424 | **75.8%** |
| `cache-codex-20260407-152003` | C (cross-process) | 5 | 1,191,713 | 981,120 | **82.3%** |
| `cache-codex-20260407-152003` | E (operator-report) | 5 | 1,582,831 | 1,323,136 | **83.6%** |
| `cache-codex-20260407-143910` | A | **1** | 349,252 | 255,232 | **73.1%** |
| `cache-codex-20260407-160753` | D2 (6 min wait) | 1 | 164,583 | 163,968 | **99.6%** |

**The key finding:** A single rep of scenario A — first call, fresh process, fresh `conversation_id` — still hits cache at 73%. There is no within-run prefix sharing to blame. The bytes have been resident on OpenAI's servers from earlier test runs and are matching automatically.

D2's 99.6% is the sharpest version of the same problem — the 6-min idle test was supposed to measure TTL boundary behavior, but it's measuring cache refresh from D1's run completing 5 min earlier. Every framework scenario is measuring the wrong thing.

The B/C/E numbers (76% / 82% / 84%) are only marginally above the contaminated A baseline, which means **whatever cache benefit `codex fork` and `codex resume` actually provide is buried inside the noise of inter-run prefix sharing**. The previous writeup that claimed "cross-process resume preserves cache better than in-process fork" is technically true but is dominated by background pollution, not by the primitives.

---

## 2. Per-vendor caching mechanics (deep research)

### 2.1 OpenAI — Codex CLI / GPT-5.4

**Mechanism**: automatic prefix caching, no client opt-in required.

**Cache key**:
- Exact byte-prefix match
- Minimum **1,024 tokens** to qualify, grows in 128-token increments
- One byte change in the first 1,024 tokens = guaranteed miss
- Per exact `model` ID — `gpt-5.4` and `gpt-5.4-mini` do not share cache
- **Org-scoped**: docs do not mention project or API-key isolation. Two processes in the same org sending byte-identical prompts within TTL **will** hit each other's cache regardless of `prompt_cache_key`, separate API keys, or process boundaries.

**TTL**:
- Standard in-memory: 5–10 min idle, max ~1 h
- Refreshed on every cache hit
- Extended `prompt_cache_retention: "24h"` available on GPT-5.1+ (offloads KV tensors to GPU-local SSD). **Codex CLI does not currently expose this** — issue [openai/codex#6698](https://github.com/openai/codex/issues/6698) closed Jan 2026 without implementing it.

**The `prompt_cache_key` parameter — critical**:
- It is a **routing hint (shard key)**, NOT a namespace isolator.
- Setting a unique value per request **does not force a cold call**.
- Quoted from OpenAI's own community forum: *"randomizing `prompt_cache_key` wouldn't reliably prevent caching. The system uses multiple routing signals; a random key would simply reduce beneficial cache reuse rather than guarantee misses."*
- Codex CLI sets `prompt_cache_key = conversation_id` at `codex-rs/core/src/client.rs:832`. A fresh `codex` invocation creates a new conversation ID — yet cache hits still happen because the prefix hash dominates routing.

**Cache attribution field**: `usage.prompt_tokens_details.cached_tokens` (Chat Completions and Responses API both).

**Codex CLI specifics**:
- Uses the **Responses API**, not Chat Completions
- Hard-codes `prompt_cache_key = conversation_id`
- Keeps system instructions, tool definitions, and environment context byte-identical and in stable order across turns (deliberately cache-friendly)
- `codex fork` / `codex resume` replay the transcript as a prefix — same byte sequence as the parent up to the fork point
- `/compact` rewrites mid-context as a summary, invalidating from that point forward but leaving the system header intact

**Documented way to force a cold call**: **none beyond mutating the first 1,024 tokens of the prefix**. From OpenAI's community forum (Jan 2026): *"As far as I know there's no way to toggle the prompt caching."* No `cache_control: 'no-cache'`, no `store: false`, no `bypass_cache` flag.

**Pricing (April 2026)**:
| Tier | Input | Cached input | Output |
|---|---:|---:|---:|
| GPT-5.4 (≤272K ctx) | $2.50/M | $1.25/M (50% off) | $15.00/M |
| GPT-5.4 (>272K ctx) | $5.00/M (2× surcharge) | ~$2.50/M | $15.00/M |

Cache discount = 50%, not the 90% I've been quoting elsewhere in this session. This contradicts earlier discussion based on stale data.

**Sources**: platform.openai.com/docs/guides/prompt-caching, openai.com/index/gpt-5-1-for-developers, community.openai.com/t/1357766, github.com/openai/codex/blob/main/codex-rs/core/src/client.rs:832, community.openai.com/t/973288, github.com/openai/codex/issues/6698

---

### 2.2 Anthropic — Claude Code / Opus 4.6

**Mechanism**: **explicit** prompt caching via `cache_control` markers on content blocks. The client must opt in per request.

**Critical for the framework**: **Claude Code sets `cache_control` markers automatically** on its outgoing requests. The markers are placed on:
- Tool definitions (the largest static block)
- System prompt (including CLAUDE.md content)
- Last content block of each user and assistant message
- (Thinking blocks are explicitly excluded)

This means Claude Code traffic is highly cacheable by default and the framework's admin API queries will see real cache attribution without any client-side intervention.

**Cache key**:
- Exact prefix match up to the marked block
- Strict order: `tools → system → messages`
- Per-model: `/model` switch invalidates all cache
- **Workspace-scoped as of Feb 5 2026** on the 1P Claude API. Before that date it was org-scoped. Bedrock and Vertex still use org scoping.
- Two workspaces in the same org **do not share cache** post Feb 5, 2026.

**Minimum cacheable prefix** (model-specific):
- Opus 4.6 / Haiku 4.5: **4,096 tokens**
- Sonnet 4.6: 1,024 tokens (docs) — community reports suggest 2,048 in practice
- Older models: 1,024 or 2,048 depending on version

**TTL**:
- Default: **5 minutes** ephemeral
- Extended: **1 hour** via `{"type":"ephemeral","ttl":"1h"}` (priced at 2× input)
- **Refreshed on every cache hit at no cost** — actively used prefixes effectively never expire
- No 24-hour tier exists as of April 2026

**Breakpoints**: max 4 explicit `cache_control` markers per request. Server also does ~20-block automatic lookback from each marker.

**Cache attribution fields** (Messages API response `usage` block):
- `cache_read_input_tokens` — tokens read from cache (billed at 0.1×)
- `cache_creation_input_tokens` — tokens written to cache on this request (billed at 1.25× or 2×)
- `input_tokens` — uncached new content for this turn (post-last-breakpoint)
- Total = sum of all three
- `cache_creation: { ephemeral_5m_input_tokens, ephemeral_1h_input_tokens }` for mixed-TTL requests

**Admin API endpoint**: `https://api.anthropic.com/v1/organizations/usage_report/messages`. Confirmed current. **Note**: at the admin API layer the field is renamed from `input_tokens` to `uncached_input_tokens`. The framework's existing parser must handle this.
- `workspace_ids[]` — confirmed parameter name (matches framework's wiring)
- `models[]` — yes, model filter exists
- `group_by[]` accepts: `api_key_id`, `workspace_id`, `model`, `service_tier`, etc.

**What invalidates Claude Code's cache**:
- `/model` switch (per-model cache)
- Toggling web search / extended thinking / fast mode
- Adding/removing an MCP server (tools block changes → invalidates everything below)
- CLAUDE.md edits
- `/rewind` or Esc-Esc (truncated prefix no longer matches stored entry)
- `/compact` (rewrites history, full miss on next turn)

**`claude --resume` and `--fork-session`**:
- **Resume**: TTL has "almost certainly expired" by the time a human resumes — effectively a cold start
- **Fork**: forked sessions share the parent's prefix → all forks benefit from the same cache entry. Documented as the cache-efficient parallel-investigation pattern.

**Documented way to force a cold call**: **none**. The only options:
- Omit `cache_control` markers (but Claude Code sets its own internally — you can't suppress them as an upstream wrapper)
- Change any byte of the prefix (a UUID in the first system block works)
- Use a different model
- Use a different workspace
- Wait past TTL with no intermediate hits

**Pricing (per 1M tokens)**:
| Model | Base input | 5m write (1.25×) | 1h write (2×) | Cache read (0.1×) | Output |
|---|---:|---:|---:|---:|---:|
| Opus 4.6 | $5 | $6.25 | $10 | $0.50 | $25 |
| Sonnet 4.6 | $3 | $3.75 | $6 | $0.30 | $15 |
| Haiku 4.5 | $1 | $1.25 | $2 | $0.10 | $5 |

Cache read is **90% off** base input. 5 min cache pays for itself after 1 read; 1 h cache after 2 reads. Opus and Sonnet 4.6 have **no separate >200K context premium** (unlike Codex's 272K surcharge).

**Sources**: platform.claude.com/docs/en/build-with-claude/prompt-caching, platform.claude.com/docs/en/api/admin-api/usage-cost/get-messages-usage-report, platform.claude.com/docs/en/about-claude/pricing, github.com/anthropics/claude-code/issues/18915, dev.to/kitaekatt/mastering-cache-hits-in-claude-code-5648

---

### 2.3 Google — Gemini CLI / Gemini 3.x

**Mechanism**: **two caches running simultaneously**:

1. **Implicit caching** — automatic, default-on for Gemini 2.5+ and 3.x, server-side prefix matching, no client action, no storage fee, 90% discount, ≤24 h TTL, project-scoped
2. **Explicit `cachedContents`** — opt-in named resource via `caches.create()`, 1 h default TTL (extendable, no max), $1.00–$4.50 per 1M tokens per hour storage fee, 90% hit discount

**Critical for the framework**: **Gemini CLI uses implicit caching only**. The official token-caching docs state: *"the Code Assist API does not support cached content creation at this time"* — meaning:
- OAuth / Code Assist users get **no caching at all**
- API-key (AI Studio) and Vertex users get **implicit caching only** (the CLI does not call `caches.create`)

**Cache key (implicit)**:
- Common-prefix match
- Token-level, ordering-sensitive (per python-genai issue #1880)
- **Project-scoped**: rotating API keys within one project does NOT give a cold cache. Rotating to a fresh GCP project does.
- Min prefix: 1,024 tokens (Flash) or 4,096 tokens (Pro tier)

**TTL**:
- Implicit: "cleared in 24 hours or less" per Vertex blog. No SLA, no floor.
- Explicit: 1 h default, configurable, no maximum (extendable via `caches.update()`)

**Cache attribution field**: `usageMetadata.cachedContentTokenCount` (camelCase docs, snake_case `cached_content_token_count` in OTel exports). This field reports **both implicit and explicit hits in the same number** — no sub-breakdown. Field is present on every `generateContent` response from both AI Studio and Vertex.

**Gemini CLI telemetry**: confirmed current — the `gemini_cli.api_response` OTel event exposes `cached_content_token_count` along with `input_token_count`, `output_token_count`, `total_token_count`, etc. Framework can write `telemetry.enabled=true` + `telemetry.target="local"` to `~/.gemini/settings.json` and read the per-call data from a local JSON-lines file with zero lag.

**`/save` and `/resume`**: client-side session-history features. Sessions stored locally (default 30-day `maxAge`). On resume the CLI **replays the transcript as a fresh prompt** — there is no server-side session ID, no inherited cache handle. Resume is just another `generateContent` call whose prefix happens to share bytes with prior calls; benefits from implicit caching only if the prefix is still in the 24 h window.

**Vertex vs AI Studio differences**:
| Dimension | AI Studio | Vertex |
|---|---|---|
| Implicit on | Yes | Yes |
| Explicit `cachedContents` | Yes | Yes |
| Implicit TTL | ≤24 h | ≤24 h |
| Storage price | $4.50/M/hr | $1.00/M/hr |
| Attribution field | `cachedContentTokenCount` | `cachedContentTokenCount` |
| **Opt-out** | **None documented** | **Project-level `cacheConfig.disableCache=true`** |
| Cache scope | Project | Project |

**Documented way to force a cold call**:
- AI Studio: **none**. No request-level flag, no project-level kill switch.
- Vertex: `PATCH publishers/google/cacheConfig { "disableCache": true }`. **Global across regions, takes effect for all traffic in the project.** Wrap each baseline run in disable / execute / re-enable. Not SLA'd; sleep 30–60 s after the PATCH.

**Pricing (per 1M tokens, April 2026)**:
| Model | Input ≤200K | Input >200K | Cached | Output ≤200K |
|---|---:|---:|---:|---:|
| Gemini 3.1 Pro Preview | $2.00 | $4.00 | $0.20 | $12.00 |
| Gemini 2.5 Pro | $1.25 | $2.50 | $0.125 | $10.00 |
| Gemini 2.5 Flash | $0.30 | $0.30 | $0.03 | $2.50 |

Explicit cache storage: **$4.50/M/hr (AI Studio)** / **$1.00/M/hr (Vertex)**.

**Cloud Monitoring metric resolution** (the `aiplatform.googleapis.com/publisher/online_serving/token_count` question I asked earlier): the metric's labels are `model_user_id`, `model_version_id`, `publisher`, `location`, `request_type`, `type` — where `type` splits `input`/`output` only, **not cached/uncached**. There is no Cloud Monitoring label that distinguishes cached from uncached tokens. Confirmed via [googleapis/python-aiplatform#4015](https://github.com/googleapis/python-aiplatform/issues/4015), an open Google issue requesting exactly this metric. Bottom line: for Gemini, the only direct cache attribution source is `usageMetadata.cachedContentTokenCount` per response (delivered via OTel for the framework's purposes).

**Sources**: ai.google.dev/gemini-api/docs/caching, docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview, docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance, github.com/google-gemini/gemini-cli/blob/main/docs/cli/telemetry.md, google-gemini.github.io/gemini-cli/docs/cli/token-caching.html, github.com/googleapis/python-aiplatform/issues/4015, github.com/googleapis/python-genai/issues/1880

---

## 3. Cross-vendor caching comparison

| Property | OpenAI / Codex | Anthropic / Claude | Google / Gemini |
|---|---|---|---|
| **Mechanism** | Automatic prefix cache | Explicit `cache_control` markers (Claude Code adds them) | Two: implicit (default on) + explicit `cachedContents` (CLI doesn't use) |
| **Cache scope** | Org | Workspace (post Feb 5 2026) | Project |
| **Min prefix tokens** | 1024 | 1024–4096 (model-specific) | 1024–4096 (model-specific) |
| **TTL** | 5–60 min in-memory; 24 h extended (Codex doesn't expose) | 5 min ephemeral; 1 h extended | ≤24 h implicit; configurable explicit |
| **TTL refreshed on hit?** | Yes | Yes (free) | Yes (assumed) |
| **Cache discount** | 50% off | 90% off (cache read) | 90% off |
| **Per-call attribution field** | `usage.prompt_tokens_details.cached_tokens` | `usage.cache_read_input_tokens` | `usageMetadata.cachedContentTokenCount` |
| **Admin/aggregate API** | `/v1/organization/usage/completions` | `/v1/organizations/usage_report/messages` | None — use BigQuery export (24 h lag) or per-call OTel |
| **Admin API lag** | ~5 min | ~5 min | n/a |
| **Documented cold-call flag** | **None** (prompt_cache_key is shard hint, not isolator) | **None** | **None on AI Studio**; project-level `cacheConfig.disableCache` on Vertex (global) |
| **Workaround for cold call** | Mutate first 1024 tokens | Mutate prefix or switch workspace | Mutate prefix or switch project (or Vertex disable) |

**The methodological universal**: **none of the three vendors offer a request-level "disable cache" parameter**. The only portable way to force a cold call across all three is to mutate the prompt prefix. This is the central finding for the redesign.

---

## 4. What the framework currently measures vs what it claims

**Claims**: "Does `codex fork` preserve the prefix cache from the parent session? Compare A (cold) against B (fork) and look at the cache hit delta."

**Actually measures**: "When the same prompt bytes have been sent to the server multiple times within the cache TTL window, the server's prefix cache hits them. This is true regardless of whether codex fork is involved."

The 64% / 76% / 82% / 84% hit rates across A/B/C/E are dominated by **inter-rep and inter-run prefix sharing**, not by the CLI primitives the scenarios are named after. The B-vs-A delta (76% > 64%) is a real signal but it's tiny relative to the 64% noise floor, and the C-vs-B delta is dominated by scenario differences (C skips the load step) rather than process-boundary effects.

**Reinterpreting prior findings**:
- ✅ **Reliable**: cache exists, byte-identical prefixes are reused
- ✅ **Reliable**: end-to-end token totals (admin API matches local SQLite to 96.7%)
- ✅ **Reliable**: wall-clock latencies
- ❌ **Unreliable**: the cache hit % numbers as evidence that any specific CLI primitive preserves cache. The hit % is dominated by background prefix sharing.

The earlier writeup claim "cross-process resume preserves cache better than in-process fork" is technically accurate in the data but the 6-point difference (76 → 82) is well within the noise floor of the 64% baseline. **It is not a strong claim and should be retracted from the cache writeup.**

---

## 5. Methodology pivot — what to test instead

### 5.1 Per-rep prefix entropy (the universal fix)

Inject a unique high-entropy nonce at the very top of the prompt prefix on every rep of every scenario. The nonce changes the byte sequence per rep, so the server's prefix cache cannot match across reps (or across runs). Within a single rep the load → ask sequence still uses the same nonce, so the cache benefit of the framework primitive is preserved if it exists.

Where to inject:
- **Codex**: prepend a `# run-id: <uuid>` line to `TIER_1_PROMPT` before sending. Since min prefix is 1024 tokens, the nonce must affect the first 1024 tokens — putting it at byte 0 ensures this.
- **Claude Code**: trickier — Claude Code controls its own outgoing request body and adds `cache_control` markers automatically. The practical lever is **CLAUDE.md content**, which Claude Code concatenates into the system prompt. Inject the nonce as the first line of CLAUDE.md per rep.
- **Gemini CLI**: prepend the nonce to the user prompt the framework sends. Gemini's implicit cache match is token-prefix and ordering-sensitive, so a nonce at the front defeats it.

Nonce should be:
- High-entropy (UUID is fine, ~40 chars / ~15 tokens)
- Padded if necessary to ensure the **first 1024 tokens differ** between reps. A UUID alone is 15 tokens — plenty to differentiate at the byte level but not enough to affect the first 1024 tokens by itself. The fix is to make the nonce semantically meaningful by embedding it in the prompt's first sentence or framing the load instruction with the nonce as a session label, so the model sees it as part of the task context, not as a magic number.
- Recorded in `results.json` per rep so the analyst can verify the bytes really were unique

### 5.2 Workspace / project rotation (Anthropic + Google)

For Anthropic and Google, the better fix is **scope rotation** rather than prefix mutation:

- **Anthropic**: cache is workspace-scoped post Feb 5 2026. Create a fresh throwaway workspace per cold rep, run the test, delete. Workspace creation is API-driven via `https://api.anthropic.com/v1/organizations/workspaces`.
- **Google Vertex**: cache is project-scoped. Two options: (a) create a fresh GCP project per cold run (heavyweight, IAM-intensive), or (b) use the documented `cacheConfig.disableCache=true` PATCH to disable for the cold run, re-enable for the warm runs.
- **Google AI Studio**: no opt-out exists. Must use prefix mutation as the workaround.
- **OpenAI**: cache is org-scoped. Cannot rotate scope in normal usage. Must use prefix mutation.

### 5.3 Negative control scenario

Add a **scenario F (negative control)**: cold load + cold ask, with a **different nonce on the load than on the ask**, in the same process. This sends two unrelated prefixes back-to-back. Should produce ~0% cache hit on both. If it doesn't, the cache is matching on common framework boilerplate (e.g., system prompt that the CLI sets which we don't control), and we have a different problem to solve before the main scenarios are valid.

### 5.4 What the redesigned scenarios should look like

| Scenario | Cold/warm | Expected cache hit % on the question op | What it actually measures |
|---|---|---:|---|
| **A** (cold, fresh nonce per rep) | Cold | **~0%** | True cold-load cost |
| **B** (load + fork + ask, same nonce within rep) | Warm | **High** | Whether `codex fork` / `--fork-session` / `/save+/resume` preserves cache |
| **C** (load + save + kill + resume + ask, same nonce within rep) | Warm | **High** | Whether cross-process resume preserves cache |
| **D-family** (TTL boundary tests, fresh nonce per rep) | Cold→Warm | Variable | TTL behavior of the underlying cache (now actually measurable) |
| **E** (operator-report repro) | Vendor-specific | TBD | Whatever the report claims |
| **F** (negative control) | Cold | **~0%** | Sanity check that the nonce mechanism works |

A clean 0% baseline (A, F) and a high warm rate (B, C, E) would be unambiguous evidence of primitive preservation. The current 64% / 76% / 82% spread is unreadable.

---

## 6. Implementation plan

### 6.1 Per-vendor changes

**Codex** (`test-cache/codex/test-cache-codex.py`):
1. Generate a UUID per rep in the rep loop (each rep of each scenario)
2. Inject `# scenario={S} rep={i} run-nonce={uuid}\n` as the first line of `TIER_1_PROMPT` before sending to `drv.send_prompt()`
3. Pad with a few hundred tokens of unique random text if needed to ensure the first 1024 tokens differ between reps
4. Record the nonce in the rep dict in `results.json` so it can be cross-referenced
5. Add scenario F implementation (cold load + cold ask with different nonces in same process)

**Claude** (`test-cache/claude/test-cache-claude.py`):
1. Same nonce-per-rep generation
2. Inject the nonce into the **CLAUDE.md** that the framework writes for each rep, since CLAUDE.md gets concatenated into Claude Code's system prompt and is the only chunk we can mutate
3. Verify via the live Messages API `usage.cache_read_input_tokens == 0` on the first call of each rep
4. **Optional alternative**: workspace rotation. Create a throwaway workspace per cold rep via the workspaces API, run, delete. Cleaner but slower.
5. Add scenario F

**Gemini** (`test-cache/gemini/test-cache-gemini.py`):
1. Same nonce-per-rep generation
2. Inject nonce into the user prompt the framework sends
3. **Critical preflight**: detect AI Studio vs Vertex auth at startup (already partly done) and warn that AI Studio has no opt-out — only nonce mutation will work
4. **Optional**: if Vertex and operator opts in via flag, use the project-level `cacheConfig.disableCache` PATCH wrapper for cold runs
5. Wire OTel telemetry capture (already designed in earlier research) to read `cached_content_token_count` per call from the local JSON-lines file
6. Add scenario F

### 6.2 Lexicon updates

1. **§5 cross-tool table** — add a "Documented cold-call mechanism" row with the per-vendor truth: "none / nonce mutation only" for Codex and Anthropic, "Vertex project disable / nonce mutation" for Google.
2. **§5.1 storage subsection** — already correct, no change.
3. **§8.2.5 evidence-source priority** — relabel from "what we trust" to "what the source actually reports." The three runtime sources (OpenAI admin API, Anthropic admin API, Gemini OTel) are all the same evidence class — server-side request-time token meters, delivered through different channels.
4. **New §8.2.7 Methodology — cold-baseline contamination** — document the inter-run cache pollution finding with the empirical 73% number from the framework's own data, the universal "nonce per rep" workaround, and the per-vendor scope-rotation alternatives.
5. **§8.7.3 Codex caching** — update from "unverified, conservative assumption is cache-cold" to "verified cache-friendly via empirical measurement on 2026-04-07; **caveat**: prior measurements were contaminated by inter-run prefix sharing and the magnitude of `codex fork` cache preservation cannot be cleanly attributed without re-running with per-rep nonces. See research.md."

### 6.3 Re-runs

Once the nonce injection is wired:

1. **Codex**: re-run `--scenario A,B,C,E,F --repetitions 5` and compare against the contaminated 152003 run. The new A and F should be near-zero; B/C/E should show the real cache benefit of each primitive.
2. **Claude**: same, after switching Claude Code to API key auth (already established this is a prerequisite for admin API evidence).
3. **Gemini**: same, after enabling OTel telemetry and switching to AI Studio API key auth (or Vertex if the operator wants `cacheConfig.disableCache` as the cold-call mechanism).

Cost estimate for the re-runs:
- Codex 5-scenario × 5-rep × ~$2/run (with cache miss, gpt-5.4 surcharge) ≈ $20–40
- Claude similar magnitude
- Gemini cheaper (~$5–10) due to lower per-token pricing

Total: ~$50–100 to get clean cache attribution data across all three vendors.

### 6.4 Analysis updates

`analyze.py` needs:
1. A check that `cache_read_input_tokens == 0` (Anthropic) / `input_cached_tokens == 0` (OpenAI) / `cachedContentTokenCount == 0` (Google) on the **first call of each "cold" rep**. Fail loudly if not.
2. A new comparison block that subtracts the F (negative control) numbers from B/C/E to isolate the primitive's contribution from any unavoidable boilerplate contamination.
3. A `cache_methodology_version: 2` field in `results.json` so analysts can distinguish runs that used the contaminated methodology from runs that used the nonce-injected methodology.

---

## 7. Open questions for the operator

1. **Re-run cost approval**: ~$50–100 across the three vendors for clean attribution. Acceptable?
2. **Anthropic workspace rotation**: do you want the heavier "create / delete workspace per rep" cleaner methodology, or just the nonce injection? Workspace rotation is more rigorous but slower (~60s overhead per rep).
3. **Gemini Vertex `cacheConfig.disableCache`**: do you want this wired as an alternate cold-call mechanism, or just rely on nonce injection? The PATCH-based approach is more rigorous but requires Vertex auth (you currently lean toward AI Studio).
4. **Sonnet 4.6 min cacheable prefix discrepancy**: docs say 1024, community reports say 2048. Verify empirically before relying on either.
5. **Lexicon §5 history-storage subsection** — was previously written; verify the corrected Gemini "file-per-session" structure I documented matches reality on all OS/version combinations.
6. **Codex `prompt_cache_retention: "24h"`**: not currently exposed by Codex CLI per issue #6698. Worth re-checking against the latest Codex CLI release if/when it ships.

---

## 8. References

### OpenAI / Codex
- platform.openai.com/docs/guides/prompt-caching
- developers.openai.com/api/docs/guides/prompt-caching
- developers.openai.com/cookbook/examples/prompt_caching_201
- openai.com/index/api-prompt-caching/
- openai.com/index/gpt-5-1-for-developers/
- community.openai.com/t/how-is-prompt-cache-key-actually-used-in-api-calls/1357766
- community.openai.com/t/is-there-a-way-to-disable-prompt-caching-in-the-apis/973288
- community.openai.com/t/new-24h-prompt-caching-retention-only-certain-models/1366221
- github.com/openai/codex/blob/main/codex-rs/core/src/client.rs (line 832: `prompt_cache_key = Some(conversation_id)`)
- github.com/openai/codex/issues/6698 (closed, `prompt_cache_retention` not exposed)
- developers.openai.com/api/docs/pricing

### Anthropic / Claude
- platform.claude.com/docs/en/build-with-claude/prompt-caching
- platform.claude.com/docs/en/about-claude/pricing
- platform.claude.com/docs/en/api/admin-api/usage-cost/get-messages-usage-report
- platform.claude.com/cookbook/misc-prompt-caching
- github.com/anthropics/claude-code/issues/18915 (1-hour TTL syntax)
- github.com/anthropics/anthropic-sdk-python/issues/1194 (Sonnet min cacheable discrepancy)
- dev.to/kitaekatt/mastering-cache-hits-in-claude-code-5648
- github.com/cline/cline/discussions/9892 (Claude Code constructs its own request body)
- support.anthropic.com/en/articles/9534590-cost-and-usage-reporting-in-console

### Google / Gemini
- ai.google.dev/gemini-api/docs/caching
- ai.google.dev/api/caching
- ai.google.dev/gemini-api/docs/pricing
- developers.googleblog.com/en/gemini-2-5-models-now-support-implicit-caching/
- developers.googleblog.com/pick-up-exactly-where-you-left-off-with-session-management-in-gemini-cli/
- docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview
- docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-create
- docs.cloud.google.com/vertex-ai/generative-ai/docs/data-governance (project-level disableCache)
- cloud.google.com/vertex-ai/generative-ai/pricing
- cloud.google.com/blog/products/ai-machine-learning/vertex-ai-context-caching
- github.com/google-gemini/gemini-cli/blob/main/docs/cli/telemetry.md
- google-gemini.github.io/gemini-cli/docs/cli/token-caching.html
- geminicli.com/docs/cli/session-management/
- github.com/googleapis/python-genai/issues/1880 (implicit cache misses on system prompt change)
- github.com/googleapis/python-aiplatform/issues/4015 (request for cache-aware Cloud Monitoring metric)
- discuss.ai.google.dev/t/urgent-huge-cost-cache-increase-issue/133912

### Framework data
- `/opt/git/ihaz_cloud/agentic-context-probe/test-output/cache-codex-20260407-152003/results.json` — the rep-5 A,B,C,E run that produced the 64% / 76% / 82% / 84% sequence
- `/opt/git/ihaz_cloud/agentic-context-probe/test-output/cache-codex-20260407-143910/results.json` — the single-rep run showing 73% on a "cold" first call
- `/opt/git/ihaz_cloud/agentic-context-probe/test-output/cache-codex-20260407-160753/results.json` — the D-family TTL test showing 99.6% on D2

### Caveats / unverified
- Sonnet 4.6 min cacheable prefix: 1024 (docs) vs 2048 (community). Empirically verify.
- Implicit Gemini cache TTL: stated as ≤24h on a Vertex blog; no SLA, no floor, no AI Studio parallel.
- Cloud Monitoring `publisher/online_serving/token_count` labels: confirmed to lack a cache-status label per issue #4015, but Google may add one without notice — re-verify before relying on absence.
- OpenAI `prompt_cache_retention: "24h"` exposure in Codex CLI: not present per issue #6698 closed Jan 2026; recheck if Codex CLI ships a major version bump.
- OpenAI cache discount magnitude: docs and pricing page say 50% off, but several earlier discussions in this session quoted 90% (citing `$2.50 / $0.25 per 1M`). The research subagent confirmed **50% is current for GPT-5.4** ($2.50 → $1.25). The earlier 90% number was either wrong or applied to an older GPT-5.0 pricing tier. Verify against current platform.openai.com/api/pricing before any cost forecasts.
