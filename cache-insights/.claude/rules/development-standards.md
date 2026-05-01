# Development Standards

Purpose: Canonical patterns for this codebase. This file is auto-loaded into every session — follow these patterns as you write code. When no pattern exists for what you're building, define one here as part of the implementation.

> This is not a reference doc you consult before coding. It's a contract that's always in context. As you write code, the patterns below are the ones you follow. If you're about to write something and there's no pattern for it, that's a signal to add one.

---

## How This Works

This file is in `rules/` — Claude Code loads it into every conversation automatically.

**When a standard exists:** Follow it. Don't invent a variation. The pattern is in your context — use it.

**When a standard exists but doesn't fit:** Flag it to the user. Either the standard needs updating or this is a justified exception. Don't silently deviate.

**When no standard exists:** You're building something new. Before (or as part of) implementing:
1. Write the CORRECT/WRONG pattern in this file
2. Point to the code you're writing as the reference implementation
3. Then continue building

The standard and the implementation happen together — not as separate steps. The code you're writing IS the first reference implementation.

---

## 0. Architecture Decisions

Locked decisions that apply across the entire codebase. Revisit only with explicit justification.

### 0.1 [Decision Name]

**Standard: [One-sentence rule.]**

[2-3 sentence rationale — why this choice, what alternatives were rejected, when to revisit.]

| Component | Choice | Rationale |
|-----------|--------|-----------|
| _[e.g., Protocol]_ | _[e.g., REST/JSON only]_ | _[e.g., Single SPA → single API, no need for GraphQL]_ |

---

## 1. Route Layer Standards

Routes are orchestration only — validate input, call service, return response. No business logic, no DB queries, no file I/O.

### 1.1 [Pattern Name]

**Standard: [Rule.]**

```python
# CORRECT
@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: UUID, auth: Auth, db: DbSession) -> ItemResponse:
    item = service.get_item(db=db, user_id=auth.user_id, item_id=item_id)
    return ItemResponse.model_validate(item)

# WRONG — [explain what's wrong]
@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: UUID, auth: Auth, db: DbSession) -> ItemResponse:
    # NO — business logic in route
    item = db.query(Item).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(404)
    return ItemResponse(id=item.id, name=item.name)
```

**Reference implementation:** `_[file:line]_`

**Current violations:** _[list files that don't follow this yet, or "None"]_

---

## 2. Service Layer Standards

Services own business logic, access control, and data operations. Every service function verifies access before touching data.

### 2.1 [Pattern Name]

**Standard: [Rule.]**

```python
# CORRECT
def create_item(db: Session, user_id: UUID, data: ItemCreate) -> Item:
    require_write_access(db, user_id, data.parent_id)
    item = Item(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

# WRONG — [explain what's wrong]
```

**Reference implementation:** `_[file:line]_`

---

## 3. Schema / Model Standards

How data shapes are defined, validated, and converted.

### 3.1 [Pattern Name]

**Standard: [Rule.]**

```python
# CORRECT
# ...

# WRONG
# ...
```

---

## 4. Frontend Standards

Component patterns, state management, and UI conventions.

### 4.1 [Pattern Name]

**Standard: [Rule.]**

```tsx
// CORRECT
// ...

// WRONG
// ...
```

---

## 5. Data Layer Standards

Migrations, queries, and schema evolution.

### 5.1 [Pattern Name]

**Standard: [Rule.]**

```sql
-- CORRECT
-- ...

-- WRONG
-- ...
```

---

## 6. Testing Standards

How tests are structured, named, and what they cover.

### 6.1 Test name reflects behavior

**Standard: Test names describe the behavior being verified, not the function under test.**

```python
# CORRECT — test name reflects behavior
def test_create_item_sets_created_by_user_id():
    ...

# WRONG — vague test name
def test_create_item():
    ...
```

### 6.2 Stub session classes belong in conftest, not duplicated per test file

**Standard: Driver-level test stubs (e.g. `_StubSession` for tmux session
mocking) live in `tests/conftest.py` as fixtures. Per-test-file stubs that
copy and slightly modify the canonical stub are a code smell.**

This codebase has multiple test files (`test_cold_warm.py`,
`test_content_growth.py`, `test_suffix_variation.py`, `test_primitive_fork.py`,
`test_primitive_rewind.py`, `test_prefix_warmup.py`) that each define their
own `_StubSession` class. The classes drift slightly (different defaults for
`name=`, varying handling of `teardown()`, etc.) — making it harder to keep
behavior consistent and harder to add a new method to all of them.

```python
# CORRECT — shared fixture in tests/conftest.py
@pytest.fixture
def stub_session_factory():
    def factory(name: str = "stub") -> _StubSession:
        ...
    return factory

# Test file consumes the shared fixture
def test_my_thing(stub_session_factory):
    session = stub_session_factory(name="forked")
    ...

# WRONG — copy-pasted _StubSession class in each test file
class _StubSession:
    def __init__(self, name: str = "stub"):
        self.name = name
        ...
    def baseline_mtime(self, **_): return None
    def send_prompt(self, text: str) -> None: ...
    # (drifts subtly: this version has teardown(), the next file forgets it)
```

**Reference implementation:** _to be promoted from `tests/tests_runner/test_cold_warm.py:22`
when refactored — file as a chore item._

**Current violations:** All 5 driver-mocking test files added 2026-04-30 —
`test_content_growth.py`, `test_suffix_variation.py`, `test_primitive_fork.py`,
`test_primitive_rewind.py`, `test_prefix_warmup.py`.

---

## 7. Error Handling Standards

How errors are raised, caught, and communicated to users.

### 7.1 Driver error-result helpers must guarantee non-empty `nonce` field

**Standard: Every driver's `_error_result` helper must produce a §6.1 result
with a non-empty `nonce` string, even when the driver fails before any nonce
is generated. The result schema enforces `minLength: 1` on `nonce` —
returning `""` causes `validate_result` to raise `ValidationError`, which
propagates through the error path and obscures the original failure.**

```python
# CORRECT — guarantee non-empty nonce in error path
def _error_result(*, vendor, model, nonces, ...) -> dict:
    nonce_repr = _join_nonces(nonces) or "<no nonces generated before failure>"
    return build_result(
        ...,
        nonce_value=nonce_repr,
        verdict="error",
        error=f"...",
    )

# WRONG — empty string fails schema validation
def _error_result(*, vendor, model, nonces, ...) -> dict:
    return build_result(
        ...,
        nonce_value=_join_nonces(nonces),  # may be "" — schema rejects
        verdict="error",
    )
```

**Reference implementation:** `cache_insights/tests_runner/prefix_warmup.py:_error_result`
(uses placeholder when `nonces` list is empty).

**Long-term fix:** Promote a shared `placeholder_nonce_for_error()` to
`_result.py` so each driver doesn't reimplement the placeholder string.
Tracked in `enhancements.md` (2026-04-28 entry).

### 7.2 Subagent prose dependency claims must be verified before encoding

**Standard: When a subagent (navigator-survey, etc.) emits enrichment text
with claims like "Blocks: <id>" or "Depends on: <id>", verify the claim by
running `bd show <id>` BEFORE encoding the dep into either the bead
description OR a `bd dep add` call.**

The navigator subagent does not validate its own dep claims against the
target bead's identity. Trusting the prose verbatim has cost real session
time (12-turn correction on `cache-insights-0to.4` when the navigator
identified `rk8.1` as the §4.2 fork consumer; the actual consumer was
`0to.7`).

```text
# CORRECT
Subagent says: "Blocks: rk8.1 (§4.2 fork test)"
→ run `bd show rk8.1` → confirm title contains "fork test"
→ if mismatch, find the actual consumer (`bd list --title-contains "fork"`)
→ THEN encode the dep

# WRONG
Subagent says: "Blocks: rk8.1 (§4.2 fork test)"
→ encode "Blocks: rk8.1" into description + run `bd dep add rk8.1 0to.4`
→ realize 6 turns later that rk8.1 is actually the §4.3 cost forecast
→ remove + re-add the correct dep
```

**Reference implementation:** _none yet — this is a new standard from
2026-04-30 retro. First implementer should embed the verification loop in
the navigator-survey agent prompt._

**Tracked in:** `enhancements.md` (2026-04-28 navigator-survey entry).

---

## Tracking Violations

When you find code that doesn't follow a standard:

1. **Don't fix it ad-hoc** — inconsistent partial fixes are worse than consistent violations
2. **Log it** as a "Current violations" note under the relevant standard
3. **Create a remediation entry**:
   Create a bead for remediation: `bd create "Remediate [standard] violations in [area]" --type chore`
4. **Batch the fix** — fix all violations of one standard together, not one at a time

---

## Adding New Standards

New standards are created during implementation, not before it. When you're writing code and no pattern exists:

1. **Write the code** — this becomes the first reference implementation
2. **Add the standard here** — CORRECT example is the code you just wrote, WRONG example is the obvious alternative you avoided
3. **Point to the file** — the reference implementation is the code from step 1
4. **Check for existing violations** — if older code does it differently, log the violations

Standards can also be promoted from `rules/standards.md` Candidate Rules when they've been validated with CORRECT/WRONG examples.

---

## When This File Changes

- **During implementation:** You're writing new code and no pattern exists → add the pattern as you build
- **During /wrapup retro:** "What should never happen again?" → new standard with the bad pattern as WRONG
- **During /quartermaster tech-review:** Audit finds inconsistency → standardize the better approach
- **When a pattern drifts:** You notice two services doing the same thing differently → pick the better one, standardize, log violations

This file grows with the codebase. If the codebase hasn't taught you anything new, there's nothing to add.
