# Phase 31: Architecture Hardening

## Objective

Consolidate intents into super-modes, elevate safety invariants to hard rules, and simplify over-specified systems for production readiness.

**Mantra:** "Feel like a product, not an OS kernel."

---

## Requirements

### R1: Intent Super-Modes

Group 13 intents into 5 conceptual super-modes:

| Super-Mode | Contains | User Perception |
|------------|----------|-----------------|
| **BUILD** | WORKITEM_CREATE, DRAFT_REFINE, DRAFT_TRANSFORM | "I'm building something" |
| **OPERATE** | JIRA_COMMAND, CHANGE_REQUEST, SYNC_REQUEST, TICKET_ACTION | "I'm managing Jira" |
| **DECIDE** | DECISION | "I'm recording a decision" |
| **THINK** | REVIEW, JIRA_SEARCH | "Help me think" |
| **CHAT** | DISCUSSION, META, AMBIGUOUS | "Just talking" |

**Implementation:**
- Keep fine-grained intents internally (for routing)
- Add `super_mode` field to IntentResult
- Update docs to present 5 modes, not 13 intents
- Simplify user-facing explanations

### R2: Two-Stage Intent Classification

Split the heavy "parse the universe" classifier:

**Stage 1: Lightweight Classifier**
```
Input: message + minimal context
Output: intent + confidence + super_mode
```

**Stage 2: Field Extractor (only when needed)**
```
Input: message + intent
Output: persona, ticket_key, command_type, etc.
```

Benefits:
- Faster for common cases (DISCUSSION, REVIEW)
- Reduces token usage
- Clearer separation of concerns

### R3: Decision Projection Invariants (Hard Rules)

Elevate these from "design notes" to **enforced invariants**:

| Invariant | Description |
|-----------|-------------|
| **MANAGED_SECTION_ONLY** | Decision projection MUST only touch `## Decisions (managed by MARO)` block |
| **FULLY_REVERSIBLE** | Every projection must be undoable by removing the managed section |
| **ISOLATED_BLOCK** | Managed section must not reference or depend on user content |

**Enforcement:**
- `update_description_with_managed_section()` must validate section boundaries
- Projection must fail if managed section cannot be cleanly isolated
- Tests must verify user content is never modified

### R4: Slack as UI, Not Authority

Canonical message failures must not corrupt state:

```
Decision approved
    ↓
DecisionStore.approve() → SUCCESS (state is truth)
    ↓
Jira sync → proceeds regardless of Slack
    ↓
Canonical message update
    ├─ SUCCESS → done
    └─ FAILURE →
        ├─ Log warning
        ├─ Decision state is still APPROVED
        ├─ Jira sync still happens
        └─ Retry message update (background)
```

**Key rule:** Slack is presentation layer. Database is truth. Jira is projection.

### R5: Canonical Message Idempotency

Message edits must be safe to retry:

| Property | Requirement |
|----------|-------------|
| **Idempotent** | Same version → same blocks (no side effects) |
| **Version-checked** | Only update if decision.version matches |
| **Failure-safe** | Edit failure doesn't change decision state |

**Implementation:**
- `update_canonical_message()` checks version before edit
- If version mismatch, log and skip (stale update)
- Retry queue for failed updates (background)

### R6: Commit Log vs State Separation

Clarify and enforce the distinction:

| Concept | Nature | Mutability |
|---------|--------|------------|
| **Canonical Message** | Current state (HEAD) | Mutable (updated in place) |
| **Commit Log** | Historical record | Append-only (never edited) |

**Rules:**
- Commit log entries are immutable after creation
- Canonical messages are updated to reflect current version
- Never merge these concepts in code or docs
- CommitStore must reject updates to existing entries

### R7: Simplified Draft Lifecycle (Optional)

Consider compressing lifecycle for v2:

**Current (Phase 28):**
```
EMPTY → SINGLE_ITEM → PLAN → PLAN_REFINED → APPROVED → COMMITTED
```

**Simplified:**
```
EMPTY → BUILDING → READY → COMMITTED
```

Sub-states derived internally:
- BUILDING + kind=SINGLE_ITEM → "collecting for one item"
- BUILDING + kind=PLAN → "collecting for multiple items"
- READY + all_items_approved → "ready to commit"

**Decision needed:** Is simplification worth migration cost?

### R8: Sync Semantics Clarity

State explicitly:

| Operation | Blocking? | Purpose |
|-----------|-----------|---------|
| **Preflight** | Yes | Guard before any Jira write |
| **/maro sync** | No | Informational reconciliation |

**Implementation:**
- Preflight is called before create/update operations
- Preflight result determines if operation proceeds
- `/maro sync` reports drift but doesn't block anything
- Add comments/docstrings stating this distinction

---

## Success Criteria

- [ ] IntentResult has `super_mode` field
- [ ] Docs present 5 modes, not 13 intents
- [ ] Two-stage classifier implemented (or decision documented)
- [ ] MANAGED_SECTION_ONLY invariant enforced with test
- [ ] Canonical message failures don't block decision approval
- [ ] Commit log entries are immutable (enforced)
- [ ] Preflight blocking vs sync informational documented
- [ ] Architecture feels like product, not kernel

---

## Non-Goals

- Renaming existing intents (backward compat)
- Removing fine-grained routing (still needed internally)
- Changing user-facing commands
- Full lifecycle simplification (evaluate only)

---

## Dependencies

- Phase 30 complete (Decision entity exists)
- Phase 29 complete (Preflight exists)
- Phase 28 complete (StructuredDraft exists)

---

*Phase: 31-architecture-hardening*
*Added: 2026-01-23*
