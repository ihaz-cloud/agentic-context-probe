# Lesson: Byte-identical fixtures contaminate cache baselines across runs

**Date:** April 2026
**Status:** Resolved — per-test nonce injection adopted as universal cold-call mechanism

## What happened

The framework's "cold baseline" scenario (A) used the same `TIER_1_PROMPT` fixture from `config.env` on every run. The fixture was byte-identical across all reps, all scenarios, and all invocations. We observed:

- Single rep of scenario A (fresh process, supposedly cold): **73% cache hit**
- Five reps of scenario A: **64% cache hit** (average)
- The "cold" baseline was never cold

## Root cause

All three vendors' prefix caches are server-side and scope to the org/workspace/project — not to the process, session, or API key:

| Vendor | Cache scope | TTL |
|---|---|---|
| OpenAI | Org | 5-60 min, refreshed on hit |
| Anthropic | Workspace (since Feb 5 2026) | 5 min default, 1 hr extended, refreshed on hit |
| Google | Project | "≤24 hours" |

Sending byte-identical bytes from a separate process 5 minutes later WILL hit the cache from the prior run. There is no vendor-supported "disable cache for this request" flag on any of the three providers.

## Impact

All cache-hit percentages from the test-cache run (`cache-codex-20260407-152003`) were contaminated:
- A: 64% (should be ~0% for a true cold baseline)
- B: 76% (inflated by inter-run sharing, not just fork preservation)
- C: 82% (same)
- E: 84% (same)

The claim "cross-process resume preserves cache better than in-process fork" was technically true in the data but the B-vs-C delta (76 → 82) was dominated by background cache pollution, not by the primitives. The finding was retracted.

## Fix: per-test nonce injection

Every test case generates a unique random nonce and injects it at the beginning of the prompt prefix. This guarantees the first 1024+ tokens have never been seen by the server's cache, regardless of what prior runs sent.

The nonce approach:
- Works on all three vendors (universal)
- Requires no vendor-specific opt-out mechanism
- Adds ~15 tokens of overhead per test (negligible)
- Enables a hard assertion: `cached_tokens == 0` on the first request, or the test is flagged as contaminated

## What we considered and rejected

1. **Workspace/project rotation** — create a fresh workspace (Anthropic) or project (Google) per cold test. More rigorous but adds 60s+ overhead and IAM complexity. Nonce injection achieves the same goal simpler.
2. **Waiting past TTL** — schedule runs hours apart. Impractical for a gate check that should take 15 minutes.
3. **OpenAI `prompt_cache_key`** — investigated as a potential namespace isolator. Turned out to be a routing hint, not a cache partition. Cannot force cold calls.
4. **Google Vertex `cacheConfig.disableCache`** — project-level kill switch exists but is global, propagation delay is not SLA'd, and doesn't exist on AI Studio.

## The meta-lesson

**If you're measuring caching, your methodology must defeat caching on the baseline.** Sending the same bytes twice and being surprised the second one is cached is a measurement error, not a cache finding. Any cache verification system must have a contamination-detection invariant: assert zero cached tokens on the first "cold" request, or fail loudly.
