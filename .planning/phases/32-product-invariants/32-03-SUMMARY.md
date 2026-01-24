---
phase: 32-product-invariants
plan: 03
subsystem: ui
tags: [slack-blocks, user-state, draft-lifecycle]

# Dependency graph
requires:
  - phase: 28-structured-draft
    provides: StructuredDraft schema with DraftLifecycle
provides:
  - UserDraftState enum with 3 user-facing states
  - get_user_state() mapping from 6 internal to 3 user states
  - user_state property on StructuredDraft
  - get_structured_draft_state_badge() for Slack UI
affects: [draft-ui, slack-handlers, approval-flow]

# Tech tracking
tech-stack:
  added: []
  patterns: [invariant-comments, user-state-mapping]

key-files:
  created: []
  modified:
    - src/schemas/structured_draft.py
    - src/slack/blocks/draft.py
    - src/slack/blocks/draft_structure.py

key-decisions:
  - "UserDraftState has 3 values: DRAFTING, READY, PUBLISHED"
  - "get_user_state() maps 4 internal states to DRAFTING, APPROVED to READY, COMMITTED to PUBLISHED"
  - "Added new get_structured_draft_state_badge() rather than breaking legacy get_draft_state_badge()"

patterns-established:
  - "INVARIANT I5: Users see 3 states only (Drafting, Ready, Published)"
  - "Internal lifecycle (6 states) hidden from UI via user_state property"

issues-created: []

# Metrics
duration: 3min
completed: 2026-01-24
---

# Phase 32 Plan 03: Draft Lifecycle 3-State Summary

**UserDraftState enum with 3 user-facing states mapping from 6 internal DraftLifecycle states**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-24T02:33:52Z
- **Completed:** 2026-01-24T02:36:24Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- UserDraftState enum with DRAFTING, READY, PUBLISHED states
- get_user_state() function mapping internal lifecycle to user state
- user_state property on StructuredDraft for easy access
- INVARIANT I5 documented in all affected files

## Task Commits

Each task was committed atomically:

1. **Task 1: Create UserDraftState enum and mapping** - `0b20a5e` (feat)
2. **Task 2: Update draft blocks to use user state** - `32dbc9f` (feat)
3. **Task 3: Update draft structure visualization** - `f941ae9` (feat)

## Files Created/Modified
- `src/schemas/structured_draft.py` - Added UserDraftState enum, get_user_state(), user_state property
- `src/slack/blocks/draft.py` - Added INVARIANT I5 comment, get_structured_draft_state_badge()
- `src/slack/blocks/draft_structure.py` - Updated header and footer to use user_state.label

## Decisions Made
- Created new get_structured_draft_state_badge() instead of modifying legacy function to maintain backward compatibility
- UserDraftState includes label and color properties for UI consistency
- Mapping: EMPTY/SINGLE_ITEM/PLAN/PLAN_REFINED -> DRAFTING, APPROVED -> READY, COMMITTED -> PUBLISHED

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness
- INVARIANT I5 fully implemented
- Draft UI now shows 3 user-facing states consistently
- Ready for Phase 32 plan 04

---
*Phase: 32-product-invariants*
*Completed: 2026-01-24*
