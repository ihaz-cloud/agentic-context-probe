# Verify lessons_learned conclusions against current design before treating them as authoritative

**Date:** 2026-04-28
**Status:** Active
**Origin:** cache-insights-e85, session aa312073-31e0-4bca-ad4f-847b3ec3d522

## What happened

While resolving the P0 decision bead `cache-insights-e85` (CLI-vs-direct-API contradiction for §4.1 cache mechanics tests), the navigator-maintenance subagent recommended Path A — "split: direct-API for §4.1, CLI for §4.2" — based primarily on the strength of `prd/lessons_learned/cli-vs-direct-api.md` having `Status: Resolved` in its header. The navigator framed the contradiction as "DESIGN.prd.md §4.1 was written without integrating the lesson, so the lesson supersedes DESIGN" and produced a plan with file edits, downstream bead reshaping, and a new direct-API client bead.

The operator pushed back with two pieces of empirical knowledge that weren't in either source document. First: prior `test-cache/{codex,claude,gemini}/` runs had actually produced trustworthy attribution data through the CLI path — the lesson's "uncontrollable bytes" framing overstated the problem. Second: DESIGN.prd.md §4.1.2 explicitly chose to handle CLI overhead by measuring it empirically per vendor/model/CLI-version (the prefix-warmup test) and treating it as a stable known constant, rather than by switching to direct API. DESIGN had engaged with the lesson's concern and made a deliberate different choice.

The lesson, not DESIGN, was the stale doc. Path B (CLI-only, lesson superseded) was correct. Going with the navigator's initial framing without verification would have triggered unnecessary doc edits, downstream bead reshaping, and creation of a direct-API-client bead that the actual design doesn't call for.

## What we learned

When a navigator or specialist cites a `lessons_learned/` doc as authoritative, do not treat the lesson as final until verified against (a) the project's chosen design (DESIGN.prd.md or equivalent) for the same topic, and (b) the operator's empirical observations from prior runs. A `Status: Resolved` header only means "the author thought it was settled at the time" — it is not proof the project agreed and locked it in. Lessons can be early-day frustrations that later experimentation invalidated, or one engineer's preferred approach that DESIGN superseded silently.

## How to apply

- When a specialist subagent cites a `prd/lessons_learned/` doc as the basis for a recommendation, before accepting: read the relevant section of DESIGN.prd.md for the same topic.
- Check specifically whether DESIGN engaged with the same concern the lesson raised and chose a different engineering response. If yes, the lesson is likely superseded — even if its header says Resolved.
- Ask the operator about prior empirical runs before assuming the lesson's "what was wrong" framing is still accurate.
- Treat `Status: Resolved` in `prd/lessons_learned/` as a strong hypothesis, not as authority. Authority is whatever DESIGN actually chose, plus what empirical runs actually showed.
- When a contradiction is found between a lesson and DESIGN: determine which was written later, what the operator's empirical knowledge says, and whether DESIGN intentionally diverged. Do not assume the later-dated doc wins automatically.
