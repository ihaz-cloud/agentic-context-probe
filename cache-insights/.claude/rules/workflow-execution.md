# Workflow: Execution

Purpose: How to implement work — branching, claiming work items, writing code, committing, and creating pull requests.

> **Terminology for this project:**
> "Work item" / "item" / "issue" throughout this file refers to a **bead** — managed via the beads (`bd`) CLI.

Use this file **during implementation**. It is the primary reference while you
are actively writing code. It covers the claim/execute checklists, branching
conventions, commit standards, and pull request creation. Do not use this file
for scoping or planning work — see `workflow-planning.md` for that.

---

## Branching Strategy

All work is done on feature branches that are merged to `main` via pull request.

### Branch Naming Convention

Create branches with a unique work ID and short description:

```
<type>/<work-id>-<short-description>
```

Types: `feature`, `fix`, `chore`, `docs`, `refactor`

Work ID format: `work-YYYYMMDD-HHMM` (timestamp-based, or sequential number)

Examples:
- `feature/work-20260323-canvas-engine`
- `fix/work-20260323-collision-bug`
- `chore/work-20260323-cleanup-imports`

### Starting a Work Session

1. **Create the work branch:**
   ```bash
   # Generate a unique work ID (use timestamp or sequential number)
   WORK_ID="work-$(date +%Y%m%d-%H%M)"
   git checkout -b feature/${WORK_ID}-<description>
   ```

2. **Associate work items with this branch:**
   - Update items to `in_progress` as you work on them
   - Any new issues discovered during work are linked via `bd create ... --discovered-from <current-id>`

### During Development

- Make atomic commits as work progresses
- Reference work items in commit messages with `Closes: <id>` (or the item's title for `none`)
- Create new work items for bugs/gaps discovered during development

---

## Claim and Execute

### Start Checklist — before writing any code:

- [ ] Item is `triage:ready` (if not, enrich first)
- [ ] `bd update <id> -s in_progress` (skip if plan-only refinement — item stays open)
- [ ] `bd comments add <id> "Effort tracking: started at turn ~N, session <session-id>"`
- [ ] `"$(git rev-parse --show-toplevel)/.claude/hooks/token-tracking.sh" start --bead <id> --phase plan --session <session-id>`
- [ ] Update `.claude/tmp/{session_id}.json` — add work item entry to `worked_beads` array (see schema below)
- [ ] Verify Effort Forecast exists on the item (see below)
- [ ] Read item description (`bd show <id>`) and capture: `priority`, `parent_epic`, `bead_created_at`, `discovered_from`
- [ ] Load context files referenced in the item

> **STOP.** Do not open any file for editing until every box above is checked.
> Every item is a command — if you can't copy-paste it, the checklist is broken.

### Verify Effort Forecast

Before transitioning to implementation, verify the work item has a **per-phase** Effort Forecast. Per-phase estimates that sum to a total give clean apples-to-apples comparison at close time.
Bead totals match what `token-tracking.sh status` reports, and single-number forecasts that conflate phases produce 3-25× false-overrun signals when compared against per-phase actuals.

1. Read the work item's description (`bd show <id>` for beads) and check for the `Effort Forecast:` section. It must list each expected phase (typical: plan, implement, test) plus a Total line.
2. If missing or single-number-only (e.g. item created before this convention), add a per-phase forecast now:
   ```bash
   bd comments add <id> "Effort Forecast (revised):
   - Plan: ~N turns, ~N tokens (rationale: e.g. reads 2 files for context)
   - Implement: ~N turns, ~N tokens (rationale: type+size historical average)
   - Test: ~N turns, ~N tokens (rationale: e.g. pytest + likely 1-2 fix iterations)
   - Total: ~N turns, ~N tokens
   - Confidence: low/medium/high"
   ```
   The "type+size historical average" rationale comes from `.claude/metrics.jsonl` — see the jq query below for how to derive per-phase averages by issue_type and issue_size.
3. Record the **summed total** as `forecast_output_tokens` and `forecast_turns` in the session tracker's `worked_beads` entry. Do not record per-phase forecasts separately in the tracker — they live in the item's description; only the total goes to the tracker for end-of-item comparison.

Consult `.claude/metrics.jsonl` for per-phase historical averages by issue_type/issue_size in one call. The query below groups by phase, so the output gives you the inputs to each line of the forecast:

```bash
jq -s '
  map(select(.issue_type == "feature" and .issue_size == "medium"))
  | group_by(.phase)
  | map({
      phase: .[0].phase,
      avg_turns: (map(.turns) | add / length),
      avg_output: (map(.actual_output_tokens) | add / length),
      samples: length
    })
' .claude/metrics.jsonl
```

To forecast a total: sum the `avg_turns` and `avg_output` across the phases the item will exercise (typically plan + implement + test). Adjust per-phase estimates up if context-loading is heavy (plan), tests are likely to need iteration (test), or the implementation crosses contract layers (implement).

Forecasts are compared against actuals in metrics.jsonl at wrapup, both per-phase and at the item-total level. Accuracy improves as data accumulates.

### Session Tracker `worked_beads` Schema

Each entry in the session tracker's `worked_beads` array is an object:

```json
{
  "bead_id": "proj-x08.28",
  "issue_type": "bug",
  "issue_size": "small",
  "cynefin_domain": "clear",
  "phase": "plan",
  "origin": "committed",
  "priority": 1,
  "parent_epic": "proj-x08",
  "discovered_from": null,
  "bead_created_at": "2026-03-28",
  "first_claimed_at": "2026-03-28T10:00:00Z",
  "forecast_output_tokens": null,
  "forecast_turns": null,
  "started": "2026-03-28T00:00:00Z",
  "stopped": null,
  "bead_closed": false,
  "metrics_written": false
}
```

- `cynefin_domain`: from `cynefin:*` label on the bead (`clear`, `complicated`, `complex`, `chaotic`, `disorder`). Null if unlabeled.
- `phase`: one of `coordinate`, `plan`, `discover`, `implement`, `test`, `fix` — see Phase Definitions below and `.claude/schemas/metrics.schema.json`

### Phase Definitions

| Phase | Starts when | Covers | Ends when |
|-------|-------------|--------|-----------|
| **coordinate** | Multiple beads selected for a sprint | Navigator survey, sequencing, presenting plan | User confirms plan |
| **plan** | Single bead claimed | Reading `bd show`, loading context files, verifying forecast | First file opened for editing |
| **discover** | Unknown encountered mid-bead requiring investigation | Researching, reading docs/code, validating assumptions | Findings captured, approach decided |
| **implement** | First file opened for editing | Writing production code AND writing test code | Last file written |
| **test** | Running verification commands | `pytest`, `tsc --noEmit`, manual AC verification | All checks pass, or failures identified requiring code changes |
| **fix** | Test/verification failure requires code changes | Editing code to resolve failures | Fix applied, ready to re-verify (transition back to `test`) |

**Typical flow:** `plan` → `implement` → `test` → done.
If tests fail: `test` → `fix` → `test` → done.
If unknowns surface: `plan` → `discover` → `implement` → `test` → done.

**Key boundary — implement vs test:** Writing tests is `implement`. Running tests is `test`. The phase transition happens when you stop editing files and start executing verification commands.

- `origin`: from session tracker arrays — `committed_beads` → `"committed"`, `carryover_beads` → `"carryover"`, `added_beads` → `"added"`, `discovered_beads` → `"discovered"`
- `priority`, `parent_epic`, `bead_created_at`, `discovered_from`: captured from `bd show` at claim time
- `first_claimed_at`: timestamp of `bd update -s in_progress`. If already in_progress from prior session, use earlier timestamp. Null for plan-only work.
- Fields not stored per-entry (`schema_version`, `session_id`, `branch`, `timestamp`) come from session tracker top-level at wrapup flush.

### Coordinate Phase

When multiple beads are selected for a sprint:

1. `token-tracking.sh start --coordinate --beads <id1>,<id2>,... --session <session-id>`
2. Run navigator survey, build sequenced plan, present to user
3. User confirms plan
4. `token-tracking.sh stop --coordinate --session <session-id>`
5. Write one worked_beads entry per bead in the batch with `phase: "coordinate"`,
   `beads_in_scope: [all bead IDs]`, `allocation_method: "equal_split"`
6. Freeze `committed_beads` and `carryover_beads` arrays

The `--coordinate` flag signals batch planning mode. `--beads` lists all beads being planned.
Token costs are split equally across beads_in_scope at query time.

If a single bead is selected: skip coordinate, go directly to plan.

### Phase Transitions

When work shifts phase mid-bead, stop the current phase and start the new one:

- `plan` → `implement`: after loading context, before first file edit
- `implement` → `test`: after last file write, before first pytest/tsc invocation
- `test` → `fix`: test failure requires code changes
- `fix` → `test`: fix applied, re-running verification

1. `token-tracking.sh stop --bead <id>`
2. Update session tracker: set `stopped` on current worked_beads entry
3. `token-tracking.sh start --bead <id> --phase <new-phase> --session <session-id>`
4. Append new worked_beads entry with the new phase and fresh `started` timestamp

This gives per-phase effort visibility without losing the bead-level rollup.

### Bead Transitions

When moving from one bead to the next within a sprint:

1. Stop tracking on current bead: `token-tracking.sh stop --bead <current-bead-id>`
2. Update session tracker: set `stopped` on current worked_beads entry
3. Start tracking on next bead: `token-tracking.sh start --bead <next-bead-id> --phase plan --session <session-id>`
4. Append new worked_beads entry for the next bead

This applies whether the current bead is being closed or paused (e.g. blocked, waiting for user input).

### Mid-Sprint Scope Changes

When the user requests dropping or swapping committed work:

1. **Drop**: move bead to session tracker `decommitted_beads`. Log: `{"action": "drop", "bead_id": "...", "reason": "...", "turn": N}` to `commitment_changes`.
2. **Swap**: log drop + add as two `commitment_changes` entries. Dropped bead goes to `decommitted_beads`, replacement goes to `added_beads`.
3. `committed_beads` stays frozen — it is the historical record of what was originally planned.

### Plan-Only Work

When the user asks to refine or spec a bead without implementing:

1. `token-tracking.sh start --bead <id> --phase plan --session <session-id>`
2. Read code, fill spec sections, write AC, size the bead, set triage state
3. `token-tracking.sh stop --bead <id>`
4. Bead stays open — not claimed with `bd update -s in_progress`
5. Append worked_beads entry with `phase: "plan"`, `bead_closed: false`

This is valid sprint work. The bead moves toward triage:ready
but is not committed for implementation this sprint.

### End Checklist — after all Acceptance Criteria checklist items pass:

- [ ] Tests written per item's Testing Strategy — diff each listed test case against actual test files before closing
- [ ] Automated verification passes (pytest, linter, type checker)
- [ ] Manual verification of each Acceptance Criteria item confirmed
- [ ] Verify tracking is clean: `"$(git rev-parse --show-toplevel)/.claude/hooks/token-tracking.sh" status --bead <id> --json` — confirm `active_phase` is null. If not, run `stop --bead <id>` and note the orphan.
- [ ] `bd comments add <id> "Token effort: plan=N impl=N test=N fix=N total=N turns=N forecast=N"`
- [ ] `bd close <id>`
- [ ] Set `bead_closed: true` on the final worked_beads entry for this item
- [ ] Commit includes `Closes: <id>` in message (for `none`: reference the item's title or stable identifier)

> Note: The structured metrics.jsonl record is written at wrapup, not here. The `token-tracking.sh stop` output is captured for the effort comment and stored in the session tracker until wrapup appends it to `.claude/metrics.jsonl`.

**When presenting a plan to the user**, include claim as step 0 and
close with effort as the final step. Plans without these steps are
incomplete.

---

## Issue Statuses

| Status | Meaning |
|--------|---------|
| `open` | Ready to start (default) |
| `in_progress` | Currently being worked on |
| `blocked` | Waiting on dependency or external factor |
| `deferred` | Postponed for later |
| `closed` | Completed |

## Execution Order

When implementing features, follow this order to minimize rework:

1. **Schema/data model** — migrations, model definitions
2. **API/service layer** — endpoints, route handlers
3. **Business logic** — service functions, validation
4. **Tests** — unit, integration, E2E
5. **Documentation** — update context files, API docs
6. **Frontend/UI** — consume the API, build the interface

## Handling Blocked Work

If work is blocked by an external factor:

```bash
bd update AES-42 --status blocked
bd comments add AES-42 "Waiting on API team for endpoint spec"
# Issue won't appear in `bd ready` until unblocked
bd update AES-42 --status open  # Unblock when ready
```

## Reopening Closed Issues

```bash
bd reopen AES-42 --reason "Bug reappeared after deploy"
```

## During Execution

- Execute each item in logical order
- Create commits as work progresses (see Commits section below)
- **Verify before closing:** After implementing an item, run the verification steps from its Acceptance Criteria and Testing Strategy sections before marking it done. At minimum:
  1. Run the project's test suite (if tests exist)
  2. Run the type checker / linter (if applicable)
  3. Manually verify each Acceptance Criteria checklist item can be confirmed
  4. If any check fails, fix the issue before closing the item
- Close items only after verification passes
- If blocked, set status to `blocked` and add a comment explaining why

## Work Discovery

When you discover unrelated issues during execution (broken tests, bugs, tech debt), **capture them immediately** rather than ignoring:

```bash
bd create "Fix broken auth tests" --type bug --discovered-from <current-bead-id>
bd create "Refactor duplicated validation logic" --type chore --discovered-from <current-bead-id>
```

**`--discovered-from` is required for all bugs.** It traces the defect back to the item whose implementation introduced it. For features and chores, `--discovered-from` is recommended but optional.

**Validate type matches description** before confirming with user:
- `bug`: fixes broken behavior ("Fix X", "X doesn't work", "X times out")
- `feature`: adds new capability ("Add X", "Implement X")
- `chore`: maintenance, no behavior change ("Clean up X", "Rename X", "Upgrade X")
- `decision`: investigates open question ("Investigate X", "Spike: X")
If the user says "create a chore" but it's fixing a failure, classify as `bug` and confirm.

**Classify the origin** and update session tracker:
- **Discovered**: surfaced by current work. Append to `discovered_beads`. If bug, set `discovered_from`.
- **Added**: user deliberately requests new scope unrelated to current work. Append to `added_beads`. Log to `commitment_changes`.
- **Do not modify `committed_beads` or `carryover_beads`** — frozen at plan confirmation.

## On Failure

If work fails:
1. Do not close the item
2. Add context via `bd comments add <id> "Error: [description]"`
3. Create follow-up items if needed
4. Seek user guidance before continuing

---

## Commits

When work results in code changes:

### Commit Message Style

Follow Conventional Commits format:

```
feat: add user login button
fix: resolve null pointer in auth handler
docs: update API documentation for auth endpoints
refactor: extract validation logic to shared module
```

### Link to Items

Reference the work item in commits when applicable:

```bash
git commit -m "feat: add login button

Closes: AES-42"
```

### Sync with Git

After completing work:

```bash
git add <specific-files>
git commit -m "feat: [description]"
bd sync
git push
```

> Always stage specific files. Avoid `git add .` — it can accidentally stage secrets, binaries, or temporary files.

### Changelog

After completing a set of features, update `changelog.yaml`.

---

## Pull Requests

When the feature branch is ready for merge:

1. **Push the branch:**
   ```bash
   git push -u origin <branch-name>
   ```

2. **Create PR using the project template:**
   ```bash
   gh pr create --title "<type>: <description>"
   ```
   Read `.github/PULL_REQUEST_TEMPLATE.md` and fill in all sections per `rules/pull-requests.md`. The `gh` CLI auto-populates the body from the template when it exists.

3. **Request human review:** After creating the PR, always request human review before merging. **NEVER merge PRs to main without explicit human approval.**

4. **Merge strategy:** Once approved, squash and merge to keep `main` history clean
