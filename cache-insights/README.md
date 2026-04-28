# Cache Insights (Goal 1)

**Goal:** Understand how prompt caching impacts cost across N providers (currently Codex, Claude, Gemini).

This is a prerequisite for Goal 2 (Context Probe). The cost of running the context probe depends on whether forking/resume primitives preserve the server-side prefix cache. If they do, the probe can load a tier once and fork N times for N questions at the cached rate. If they don't, every question pays full load cost.

## Key questions

1. Does the cache work as documented? (per vendor)
2. Do CLI primitives (fork, rewind) preserve cache? (per vendor)
3. What's the effective cost model? (per vendor, per strategy)

## Structure

```
cache-insights/
  README.md                      # This file
  verify-local-sources.py        # Utility — verifies local attribution sources per vendor
  prd/                           # Everything needed to build from scratch
    DESIGN.prd.md                # Product requirements
    pricing.toml                 # Per-vendor per-model token pricing (pinned April 2026)
    research.md                  # Deep research findings (3 vendors)
    lexicon.prd.md               # Vendor reference (shared with Goal 2)
    config.env                   # Model defaults, vendor config
    otel-collector-config.yaml   # Codex OTel prerequisite
    lessons_learned/             # Documented assumption changes from investigation
  .archive/                      # Superseded items from earlier approaches
```

## Getting started

1. Read `prd/DESIGN.prd.md` — the product requirements.
2. Run `python3 verify-local-sources.py` — confirms local attribution sources are available per vendor.
3. Complete the one-time prerequisites in `prd/DESIGN.prd.md` §5.3 (Codex OTel, Gemini telemetry).
4. Build against the capabilities described in §4.

## Providers

| Provider | CLI | Cache attribution source | Cache type |
|---|---|---|---|
| OpenAI | Codex CLI (`codex`) | OTel logs via local collector | Automatic prefix cache, org-scoped |
| Anthropic | Claude Code (`claude`) | Session JSONL (always written) | Explicit `cache_control` markers (CLI sets automatically) |
| Google | Gemini CLI (`gemini`) | OTel telemetry log (opt-in) | Implicit (default-on) + explicit `cachedContents` |
