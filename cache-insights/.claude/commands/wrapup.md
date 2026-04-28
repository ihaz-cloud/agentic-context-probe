---
description: Full session wrapup — verify, commit, update work items, handoff with progress, retro
tier: scale
version: 2.1.0
created: 2026-03-21
changelog:
  - 2.1.0 (2026-04-25): Wrap token-tracking flush in metrics:on blocks; upgrade to status-check + jq metrics.jsonl flush
  - 2.0.0 (2026-03-21): Full rewrite — TaskCreate enforcement, beads validation, token tracking, context doc checklist
  - 1.1.0 (2026-03-21): Add tracker-conditional blocks, env health check updates
  - 1.0.0 (2026-03-21): Initial tiered version
---

# /wrapup — Full Session Wrapup

> **Philosophy:** No wrap-up, no merge. If you don't wrap up, your next session starts by rediscovering decisions.

**IMPORTANT: You MUST use TaskCreate to create a task for EVERY checklist item below BEFORE starting any work. Then use TaskUpdate to mark each task `in_progress` when you start it and `completed` when done. Do NOT skip any task — if a step is not applicable, mark it completed with a note explaining why. The user can see task progress and will hold you accountable for completing every item.**

Create all tasks first, then work through them in order:

---

### Task 1: Archive Plan Files

If a plan was created during this session, ensure it's saved to `.archive/plans/`:

- Check if a plan file exists for the current work
- Save/move to `.archive/plans/<feature-name>.md` using the naming convention:
  - Strip `feature/` or `fix/` prefix from branch name
  - Strip work ID prefix (`work-YYYYMMDD-` or similar)
  - Use remaining description as filename
  - Example: `feature/work-20260321-auth-flow` → `.archive/plans/auth-flow.md`
- Ensure all work items from the plan exist as beads
- Add plan context as comments on relevant beads: `bd comments add <id> "Plan context: <summary>"`
- Plans persist after branch merge for historical reference
- **If no plans were created:** mark completed with "No plans to archive"

### Task 2: Build Verification

**No green, no commit.**

Run the full verification suite. Read `architecture.md` or `package.json` / `Cargo.toml` / `pyproject.toml` to determine the correct commands:

- **Typecheck:** if applicable (e.g., `npx tsc --noEmit`, `mypy .`)
- **Tests:** project test runner (e.g., `npm test`, `pytest tests/ -q`, `cargo test`)
- **Linter:** project linter (e.g., `npm run lint`, `ruff check .`)
- **E2E tests:** if configured (e.g., `npm run test:e2e`, `npx playwright test`)
  - If E2E tests fail due to infrastructure (backend/frontend not running), note it and skip
  - If E2E tests fail due to actual regressions, fix before committing
- **Bead lint:** run `bd lint` on any beads closed this session to validate completeness

**Do NOT proceed to commit if builds fail — fix first.**

### Task 3: Beads Issue Updates

Update issue tracking for work completed this session:
- **Close completed:** `bd close <id>` for finished work
- **Update in-progress:** `bd update <id> --status in_progress` for partial work
- **Create follow-ups:** `bd create "<title>"` for discovered work items
- **Add comments:** `bd comments add <id> "<note>"` with implementation details or decisions made
- **Validate effort forecasts:** `bd comments add <id> "Effort: forecast=N actual=N"` — compare estimated vs actual
- **If no beads changed:** mark completed with "No beads to update"

### Task 3b: Validate Beads

For each bead created or touched this session, run the readiness checklist:
- [ ] `bd lint <id>` — no warnings (acceptance criteria, required sections)
- [ ] **Effort Forecast: per-phase breakdown** present (plan/implement/test minimum + Total + Confidence) per `work-item-templates.md` Effort Forecast contract — single-number forecasts must be revised before the item can reach `triage:ready`
- [ ] Priority assigned
- [ ] Epic parent assigned (or justified as standalone)
- [ ] Dependencies set if sequencing matters

Then:
- **Assign orphaned beads** to existing epics using `bd dep add <bead-id> <epic-id> -t parent-child`
- If no existing epic fits, evaluate whether a new epic is warranted (3+ related orphans) or leave as standalone
- Run `bd epic status` to verify epic health after assignments
- **If no beads created or touched:** mark completed with "No beads to validate"

### Task 3c: Finalize Token Tracking

Review `.claude/tmp/{session_id}.json` and finalize token data:

1. **Check tracking status** for each unique `bead_id` in `worked_beads`:
   `.claude/hooks/token-tracking.sh status --bead <bead-id> --json`
2. **If `active_phase` is null** — properly stopped. Proceed to step 4.
3. **If `active_phase` is not null** — orphan. Run:
   `.claude/hooks/token-tracking.sh stop --bead <bead-id> --json`
   Mark all segments from this stop as `orphaned: true` in metrics.jsonl. Warn in wrapup report.
4. **Set stopped timestamps** on all open `worked_beads` entries.
5. **Add effort comments** to any beads missing them via `bd comments add`.
6. **Append to `.claude/metrics.jsonl`** — one JSON line per segment in `sessions[<session_id>].segments` from the status/stop output, where `metrics_written: false`. **Always pipe through `jq -c`** to guarantee valid JSON:
   ```bash
   jq -n -c \
     --arg bead_id "..." \
     --arg session_id "..." \
     --arg issue_type "..." \
     --arg issue_size "..." \
     --arg cynefin_domain "..." \
     --arg phase "..." \
     --arg origin "..." \
     --arg branch "..." \
     --argjson forecast_output N_OR_NULL \
     --argjson forecast_turns N_OR_NULL \
     --argjson actual_output N \
     --argjson actual_input N \
     --argjson cache_read N \
     --argjson cache_create N \
     --argjson turns N \
     --arg started "ISO" \
     --arg stopped "ISO" \
     --arg bead_created_at "YYYY-MM-DD" \
     --argjson bead_closed false \
     --argjson priority N_OR_NULL \
     --arg parent_epic "STRING_OR_EMPTY" \
     --arg discovered_from "STRING_OR_EMPTY" \
     --argjson orphaned false \
     '{schema_version:1, bead_id:$bead_id, session_id:$session_id,
       issue_type:$issue_type, issue_size:$issue_size, cynefin_domain:$cynefin_domain, phase:$phase,
       origin:$origin,
       beads_in_scope:[], allocation_method:null,
       branch:$branch, forecast_output_tokens:$forecast_output, forecast_turns:$forecast_turns,
       actual_output_tokens:$actual_output, actual_input_tokens:$actual_input,
       actual_cache_read_tokens:$cache_read, actual_cache_create_tokens:$cache_create,
       turns:$turns, started:$started, stopped:$stopped, orphaned:$orphaned,
       bead_created_at:$bead_created_at, bead_closed:$bead_closed, priority:$priority,
       parent_epic:(if $parent_epic == "" then null else $parent_epic end),
       discovered_from:(if $discovered_from == "" then null else $discovered_from end),
       timestamp:(now | strftime("%Y-%m-%dT%H:%M:%SZ"))}' \
     >> .claude/metrics.jsonl
   ```
   - `issue_size`: the bead's size label (`small`, `medium`, `large`, or `null` if unlabeled)
   - `origin`, `bead_created_at`, `priority`, `parent_epic`, `discovered_from`: read directly from the matching `worked_beads` entry in the session tracker (see `rules/workflow-execution.md` Session Tracker `worked_beads` Schema). Pass an empty string for `parent_epic` / `discovered_from` when the tracker entry is `null` — the jq expression maps `""` back to `null`.
   - `bead_closed`: `true` only if `bd close <id>` ran for this bead this session (final record per bead). False otherwise.
   - Multi-bead planning: set `allocation_method: "equal_split"`, include `beads_in_scope`
   - For orphaned segments: set `orphaned: true`
   - After appending, flip `metrics_written: true` in session tracker (idempotent reruns)
7. **Verify flush** — run: `tail -20 .claude/metrics.jsonl | jq -r '.bead_id' | sort -u` and confirm every bead from `worked_beads` appears. If any are missing, the flush is incomplete — go back to step 6.
8. **Delete** `.claude/tmp/{session_id}.json` after metrics are written
- **If no session tracker** (ad-hoc session): mark completed with "No session tracker — ad-hoc session"

### Task 4: Log Documentation Enhancements

**Run this BEFORE updating any `.claude/*.md` files.**

Review the session and log documentation gaps discovered to `.claude/enhancements.md`:
- Did you need information that wasn't in `.claude/*.md` and had to discover it from source code or trial-and-error?
- Log new gaps using the template in `enhancements.md`: what was needed, where the gap is, suggested fix
- Categories to check: data model, API routes, business logic, frontend components, schemas/types, process
- **If no gaps discovered:** mark completed with "No documentation gaps to log"

### Task 5: Update changelog.yaml

**Prepend** a new entry to the top of the `entries:` list in `.claude/changelog.yaml`. Use the `template_entry` as the format reference:

```yaml
- version: "0.X.Y"
  date: "YYYY-MM-DD"
  branch: "<current-branch-name>"
  focus: [feature, bugfix, refactor, infrastructure, documentation, stabilization]
  summary: "<one-line summary>"
  beads: [bead-id-1, bead-id-2]
  backend:
    - "added: description"
    - "fixed: description"
  frontend:
    - "changed: description"
  infra:
    - "added: description"
  docs:
    - "added: description"
```

- Omit area keys that have no changes (don't write empty lists)
- Prefix each bullet with `added:`, `changed:`, or `fixed:`
- **Lint:** Run `yq '.' .claude/changelog.yaml > /dev/null` to validate YAML
- **Verify:** Run `yq '.entries[0].summary' .claude/changelog.yaml` to confirm
- **If no features/fixes completed:** mark completed with "No changelog entries needed"

### Task 6: Update Context Docs

Check if this session changed any source code paths and update the corresponding `.claude/*.md` file:

| Changed path | Update |
|-------------|--------|
| Models, migrations, schemas | `data-model.md` |
| API routes, new endpoints | `backend.md` |
| Dependencies (package.json, pyproject.toml, etc.) | `architecture.md` Technology Decisions |
| Directory structure | `architecture.md` Directory Structure |
| Pages, components, UI | `frontend.md` |
| Dev tools, scripts | `architecture.md` Developer Tools |

Also review open (non-`[RESOLVED]`) entries in `.claude/enhancements.md` and apply fixes to the target docs. After applying, mark entries `[RESOLVED]`.

- **If no changes:** mark completed with "No context doc updates needed"

### Task 7: Git Commit & Push

- **NEVER commit directly to `main`.** All work MUST be on a feature branch.
  - If on `main`, create a branch first: `git checkout -b feature/work-YYYYMMDD-<short-description>`
- Run `git status` to check for uncommitted changes
- Stage and commit using Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- Reference bead IDs in commit messages: `feat: add auth flow [BD-12]`
- Run `bd sync` to sync beads (**never on main** — use `bd sync --no-push` if on main)
- Run `git pull --rebase` to catch remote changes
- Run `git push -u origin <branch>`
- **Critical:** Work is not complete until push succeeds. If push fails, resolve and retry.
- Verify: `git status` must show "working tree clean"
- **Do NOT create a PR automatically.** Only create when explicitly asked.

### Task 8: Session Summary & Handoff

**Prepend** a new entry to the top of the `entries:` list in `.claude/handoff.yaml`. Use the `template_entry` as the format reference:

```yaml
- date: "YYYY-MM-DD HH:MM UTC"
  branch: "<current-branch-name>"
  focus: [feature, bugfix, refactor, infrastructure, documentation, stabilization]
  completed:
    - "item-id: what was accomplished"
  discovered:
    - "item-id: new work filed this session"
  in_progress:
    - "item-id: current state of partial work"
  blockers:
    - "item-id: what's stuck and why"
  next_steps:
    - "item-id: what to do next, in priority order"
  epic_progress: "epic-id XX% → YY%"
  commits: ["abc1234", "def5678"]
  token_usage:
    metrics_file: ".claude/metrics.jsonl"
    beads_tracked: ["item-id-1", "item-id-2"]
```

- Omit keys that are empty (don't write empty lists)
- `token_usage` references metrics.jsonl for detailed per-bead data; handoff only lists which beads were tracked
- Omit `token_usage` entirely for ad-hoc sessions
- **Lint:** Run `yq '.' .claude/handoff.yaml > /dev/null` to validate YAML
- **Verify:** Run `yq '.entries[0].date' .claude/handoff.yaml` to confirm
- Display the summary inline so the user sees it immediately
- End with: "Ready to resume. Next session: [specific task] (see issue <id>)"

### Task 9: Retro (recommended)

Ask the user these questions and wait for responses:

1. **What went well this session?** — Reinforce good patterns.
2. **What burned time?** — Capture as a follow-up work item or enhancement in `.claude/enhancements.md`.
3. **What should never happen again?** — If actionable, add as a CORRECT/WRONG pattern in `rules/development-standards.md`. Do NOT modify `rules/workflow.md` — that file is kit-managed and will be overwritten by updates.
4. **Were any beads underspecified when you started implementing?** — Note the gap in `.claude/enhancements.md` with a suggested improvement to the readiness checklist.
5. **Were any effort forecasts significantly off?** — Note the variance in `.claude/enhancements.md` so sizing calibration can be reviewed.

### Task 10: Update Environment Health Checks

If this session added, removed, or changed infrastructure (new service, new port, new dependency, docker-compose changes, new .env variables):

1. Read the **Environment Health Checks** table in `.claude/architecture.md`
2. Update it to reflect the current state:
   - Add rows for new services (with check command + expected output)
   - Remove rows for decommissioned services
   - Update check commands if ports or endpoints changed
3. Update the "Local Development" commands if startup steps changed

This ensures `/leroy` and `/gogogo` check the right services in future sessions.

- **If no infrastructure changes:** mark completed with "No env check updates needed"

### Task 11: Improve Session Startup (optional)

Evaluate if anything learned during this session should improve `/gogogo` or `/leroy`:
- New context files that should be loaded at startup
- Additional checks that would have been helpful
- Environment variables or dependencies that caused issues

If improvements are identified, note them in `.claude/enhancements.md` for review.
- **If no improvements identified:** mark completed with "No startup updates needed"
