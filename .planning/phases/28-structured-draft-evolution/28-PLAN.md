# Phase 28: Structured Draft Evolution - Master Plan

**Mantra:** Draft is a data structure representing the shape of work, not a paragraph of text.

**Core Shift:** From "bot collects text for a ticket" to "bot manages the form of a design object and the evolution of its structure."

---

## Overview

This phase transforms the TicketDraft from a text container into a typed, versioned design object with:
- **Kind** (SINGLE_ITEM vs PLAN)
- **Scope** (SINGLE, EPICS_ONLY, FULL_PLAN)
- **Lifecycle** (EMPTY → SINGLE_ITEM → PLAN → PLAN_REFINED → APPROVED → COMMITTED)
- **Items** (list of DraftItems with their own status)
- **Change Log** (versioned structural changes)

## Architecture Impact

### Current State (TicketDraft)
```python
class TicketDraft:
    title: str
    problem: str
    issue_type: IssueType  # Single type
    requested_scope: RequestedScope  # Scope hint
    version: int
    # ... fields for one ticket
```

### Target State (StructuredDraft)
```python
class StructuredDraft:
    kind: DraftKind  # SINGLE_ITEM vs PLAN
    scope: DraftScope  # SINGLE, EPICS_ONLY, FULL_PLAN
    lifecycle: DraftLifecycle  # State machine position
    version: int
    items: list[DraftItem]  # Multiple items with structure
    change_log: list[DraftChange]  # Every mutation logged
```

## Sub-Phases

| Phase | Focus | Risk | Key Deliverables |
|-------|-------|------|------------------|
| 28.1 | Core Schema + Data Migration | High | StructuredDraft schema, DraftKind, DraftScope, DraftLifecycle, migration from TicketDraft |
| 28.2 | DRAFT_TRANSFORM Intent | Medium | New intent detection, semantic triggers, route to transform flow |
| 28.3 | Structural Mutation Engine | High | Mutations for split/merge/elevate/decompose, change log |
| 28.4 | Lifecycle State Machine | Medium | Enforce transitions, validation depends on lifecycle |
| 28.5 | User Input Classification | Medium | Classify choice vs opinion vs question, action routing |
| 28.6 | Structure Feedback UI | Low | Show structure after changes, version-bound buttons |

## Dependency Graph

```
28.1 (Schema) ─────┬──► 28.2 (Intent) ──► 28.3 (Mutations)
                   │                             │
                   └──► 28.4 (Lifecycle) ◄───────┘
                             │
                   ┌─────────┴─────────┐
                   ▼                   ▼
           28.5 (Classification)  28.6 (UI)
```

**Wave Structure:**
- Wave 1: 28.1 (foundation)
- Wave 2: 28.2 (parallel with 28.4)
- Wave 3: 28.3 (needs 28.2)
- Wave 4: 28.4 finalization, 28.5, 28.6 (parallel)

## Requirements Mapping

| Requirement | Sub-Phase | Description |
|-------------|-----------|-------------|
| R1 | 28.1 | Draft must be typed object |
| R2 | 28.3 | User decisions mutate Draft form |
| R3 | 28.5 | Bot transitions from questions to action |
| R4 | 28.2 | New intent: DRAFT_TRANSFORM |
| R5 | 28.4 | Draft must have lifecycle |
| R6 | 28.4 | Validation depends on Draft form |
| R7 | 28.5 | Distinguish choice/opinion/question |
| R8 | 28.6 | Show new form after each change |
| R9 | 28.1 | Draft must be versioned |
| R10 | 28.5 | No question repetition after direct answer |
| R11 | 28.3 | Transition from decision to action mandatory |
| R12 | 28.1 | Draft is "design model" not "text draft" |

## DoD Tests (from REQUIREMENTS.md)

### T1: Structural decision mutates state
1. User says "Split into epics"
2. Draft.kind changes from SINGLE_ITEM to PLAN
3. Draft.version increments
4. Bot shows new structure

### T2: Lifecycle enforced
1. Draft is in PLAN stage
2. Bot asks about decomposition (not acceptance criteria)
3. Only when item_type=STORY does bot ask AC

### T3: No question repetition
1. User answers "Only epics"
2. Bot does NOT ask "Would you like epics or full plan?" again
3. Draft.scope = EPICS_ONLY is locked

### T4: Version-bound approvals
1. Show preview (version=3)
2. User transforms structure (version=4)
3. Old approve button → "Outdated, please review new structure"

### T5: Form-dependent validation
1. Epic draft → validate goal, scope
2. Story draft → validate acceptance criteria
3. Plan draft → validate item count, decomposition logic

## Migration Strategy

**Backward Compatibility:**
- TicketDraft remains functional during migration
- New StructuredDraft wraps/extends TicketDraft
- Existing drafts auto-migrate to StructuredDraft(kind=SINGLE_ITEM, items=[converted_item])
- Gradual rollout: feature flag for new draft behavior

## Risk Mitigation

1. **Data Migration Risk** - Keep TicketDraft working, add StructuredDraft alongside
2. **State Machine Complexity** - Extensive unit tests for lifecycle transitions
3. **UI Complexity** - Incremental: first show structure text, then rich blocks
4. **Intent Confusion** - DRAFT_TRANSFORM distinct from DRAFT_REFINE (Phase 26)

## Files Affected (Preview)

### New Files
- `src/schemas/structured_draft.py` - StructuredDraft, DraftKind, DraftScope, DraftLifecycle, DraftItem, DraftChange
- `src/graph/nodes/draft_transform.py` - Structural mutation handlers
- `src/slack/blocks/draft_structure.py` - Structure visualization blocks

### Modified Files
- `src/schemas/draft.py` - Add migration helpers
- `src/schemas/state.py` - Add StructuredDraft to AgentState
- `src/graph/intent.py` - Add DRAFT_TRANSFORM detection
- `src/graph/graph.py` - Add transform flow routes
- `src/graph/nodes/decision.py` - Lifecycle-aware decisions
- `src/graph/nodes/validation.py` - Form-dependent validation
- `src/graph/nodes/extraction.py` - Extract structural decisions
- `src/slack/handlers/dispatch.py` - Handle transform UI events

---

## Next Steps

1. Create 28.1-PLAN.md (Core Schema + Data Migration)
2. Execute sequentially due to high risk
3. Extensive testing at each sub-phase boundary

**Execute:** `/gsd:execute-plan 28.1` after plan creation
