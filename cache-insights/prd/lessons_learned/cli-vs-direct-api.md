# Lesson: Cache mechanics should be tested via direct API, not through the CLI

**Date:** April 2026
**Status:** Superseded (2026-04-28) — see "Why this was superseded" below. The current design (DESIGN.prd.md §4.1) tests cache mechanics through the CLI via tmux and addresses the byte-control concern with the §4.1.2 prefix-warmup baseline rather than by switching to direct API.

## Why this was superseded

This lesson framed CLI overhead (system prompts, tool definitions, conversation framing) as "uncontrollable" and concluded that cache mechanics must be measured via direct API for byte-level control. DESIGN.prd.md §4.1.2 took a different engineering choice: measure CLI overhead empirically per vendor / model / CLI version (the prefix-warmup test), treat it as a stable known constant, and baseline subsequent measurements against it. Prior `test-cache/{codex,claude,gemini}/` runs produced trustworthy attribution data through this path, validating the choice empirically.

The CLI-driven path also matches what the downstream Context Probe actually invokes (the CLIs themselves), so cache figures observed through the same surface are more directly relevant to the cost forecast than figures from a parallel direct-API path.

One narrow gap remains and is intentional: Codex's extended-TTL feature (`prompt_cache_retention`, 24h) is exposed only at the API layer, not by the Codex CLI. DESIGN.prd.md §7.1 documents this as out of scope; §4.1 verifies the default in-memory TTL (5-60 min) only.

The salvage table below ("What was salvageable") still describes which artifacts from the original CLI-driven `test-cache/` work fed forward — that section remains accurate regardless of the direct-API-vs-CLI conclusion.

## Original lesson (preserved for historical context)

**Original status:** Resolved — cache-mechanics.py uses direct API calls; CLI reserved for primitive validation only

## What we built first

The original `test-cache/{codex,claude,gemini}/` scripts drove each CLI through tmux to test caching behavior. This involved:
- tmux session management (launch, paste-buffer, send-keys, capture-pane)
- TUI footer parsing for token deltas
- `/status` panel scraping (later made optional)
- Timing constants (LAUNCH_READY_WAIT_S, STATUS_RENDER_WAIT_S, PASTE_SETTLE_S)
- ANSI stripping and Unicode box-drawing translation
- OpTimer classes tracking pre/post state per operation
- Per-vendor harness classes (CodexHarness, GeminiHarness)

## Why this was the wrong approach for cache measurement

The CLI adds uncontrollable bytes to every request:
- System prompts (including CLAUDE.md, agent instructions)
- Tool definitions (file tools, shell tools, MCP tools)
- Conversation history formatting
- Vendor-specific framing (Codex sets `prompt_cache_key`, Claude adds `cache_control` markers)

When measuring "does the cache work," you need to control the exact bytes sent. The CLI makes that impossible — you can control the user prompt but not the 50K+ tokens of system/tool preamble the CLI wraps around it.

For measuring "does `codex fork` preserve the cache," you DO need the CLI because fork is a CLI primitive. But that's a narrow question (6 test cases) vs the broad cache characterization (cold/warm, TTL, boundaries, byte-change sensitivity) that dominates the work.

## What we do instead

| Question | Tool | Why |
|---|---|---|
| Does the vendor cache work as documented? | `cache-mechanics.py` — direct API calls | Full byte control, no CLI noise |
| What's the TTL? | `cache-mechanics.py` | Need precise timing, no process-startup jitter |
| What's the minimum cacheable prefix? | `cache-mechanics.py` | Need exact token count control |
| Does fork preserve cache? | `primitive-validator/` — CLI via tmux | Fork is a CLI primitive, can't test without the CLI |
| Does rewind preserve cache? | `primitive-validator/` — CLI via tmux | Same — rewind is in-session only |

## What was salvageable from the CLI-driven scripts

- Per-vendor auth-mode detection (OAuth vs API-key) — useful context, moved to lessons_learned
- The lexicon updates about storage layouts, footer configs, telemetry paths — kept in lexicon.prd.md
- The OTel/JSONL local source discovery — became the per-call attribution path for primitive validation
- The pricing research and vendor comparison tables — kept in DESIGN.prd.md §6.2 and research.md

## What was not salvageable

- The A/B/C/D/E scenario framework — conflated cache mechanics with CLI integration testing
- The tmux-based OpTimer/harness infrastructure — overbuilt for what turned out to be 6 targeted test cases
- The incremental results.json persistence and admin API pre/post snapshot pattern — replaced by local file reads
- The footer scraping, ANSI stripping, and box-drawing translation — unnecessary when reading structured JSON from local files

## The meta-lesson

**Separate "does the vendor's API work as documented" from "does our CLI tooling interact with it correctly."** The first is a pure API question best answered by direct API calls with controlled input. The second is a CLI integration question that needs the CLI. Building one system to answer both questions produces a system that answers neither cleanly.
