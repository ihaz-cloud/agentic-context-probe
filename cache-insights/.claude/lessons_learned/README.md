# Lessons Learned (process / meta)

Purpose: Capture **process and meta-lessons** about how we work on this project — how we use docs, how we coordinate with subagents, how we plan work items, what mistakes recur. These are durable, in-repo replacements for ephemeral assistant memory.

> **Two `lessons_learned/` folders, two different purposes:**
> - `prd/lessons_learned/` — **domain/product lessons.** What we learned about vendor APIs, cache mechanics, telemetry surfaces, primitive behavior. Authority over what we build. Examples: `cli-vs-direct-api.md`.
> - `.claude/lessons_learned/` — **process/meta lessons.** How to work on the project effectively, how to use the existing docs, how to avoid repeated coordination mistakes. Authority over how we work, not what we build.
>
> If unsure: a lesson belongs in `prd/` if it changes what the harness *does*; in `.claude/` if it changes what a future session *should know about working here*.

---

## What to write here

Add a lesson when:

- An operator correction reveals a recurring pattern that future sessions need to know (e.g., "verify X against Y before treating Z as authoritative")
- Subagent output framed something incorrectly and the correction is generalizable
- A coordination decision was made that won't be obvious from code or git history (e.g., "we keep `prd/` and `.claude/` separate because…")
- A failure mode in our own workflow was identified and a guardrail decided

Do not write:

- Code conventions (those go in `.claude/rules/standards.md`)
- Architectural decisions about the harness itself (those go in `prd/lessons_learned/` or `prd/DESIGN.prd.md`)
- Status updates or session summaries (those go in `.claude/handoff.yaml`)

---

## File format

One lesson per file. Keep titles descriptive — they're the index.

```markdown
# <Lesson title>

**Date:** YYYY-MM-DD
**Status:** Active | Superseded — see <link> | Archived
**Origin:** <bead-id, session, or PR that surfaced this>

## What happened

<2-3 paragraphs on the situation that produced the lesson.>

## What we learned

<The durable rule or guardrail. State it as a directive future sessions can apply.>

## How to apply

<Concrete trigger conditions and the action to take.>
```

If a later session invalidates the lesson, change `Status` to `Superseded` and add a forward link rather than deleting — the history is part of the value.
