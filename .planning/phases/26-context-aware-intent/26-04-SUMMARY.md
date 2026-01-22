---
phase: 26-context-aware-intent
plan: 04
subsystem: graph
tags: [decision, intent, routing, draft-refine]

# Dependency graph
requires:
  - phase: 26-02
    provides: DRAFT_REFINE intent classification
  - phase: 26-03
    provides: Extraction of issue_type and scope signals
provides:
  - draft_refine action in DecisionResult
  - DRAFT_REFINE handling in decision_node
  - Context-aware refinement prompt generation
  - Graph routing for draft_refine action
affects: [slack-handlers, response-generation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Intent-based decision routing in decision_node"
    - "Context-aware prompt generation for draft refinement"

key-files:
  created: []
  modified:
    - src/graph/nodes/decision.py
    - src/graph/graph.py

key-decisions:
  - "draft_refine routes to END like other decision actions (Slack handler processes)"
  - "_build_refinement_prompt offers scope options based on draft type (Epic vs Story)"

patterns-established:
  - "Intent-specific handling in decision_node before validation checks"

issues-created: []

# Metrics
duration: 8min
completed: 2026-01-22
---

# Phase 26 Plan 04: Draft Continuity Rule Summary

**Decision node respects DRAFT_REFINE intent, routing meta-questions about active draft to context-aware refinement response instead of review mode**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-01-22T20:06:00Z
- **Completed:** 2026-01-22T20:14:04Z
- **Tasks:** 5
- **Files modified:** 2

## Accomplishments

- Added `draft_refine` action to DecisionResult with `refinement_prompt` field
- Implemented DRAFT_REFINE intent handling in decision_node before other checks
- Created `_build_refinement_prompt` helper that generates context-aware options based on draft type
- Updated `get_decision_action` to return `draft_refine` for routing
- Added `draft_refine` route in graph conditional edges (routes to END)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add draft_refine action to DecisionResult** - `c4583b7` (feat)
2. **Task 2-3: Handle DRAFT_REFINE intent + helper** - `75b3eaa` (feat)
3. **Task 4: Update get_decision_action** - `5459656` (feat)
4. **Task 5: Add draft_refine route in graph** - `2641970` (feat)

## Files Created/Modified

- `src/graph/nodes/decision.py` - Added draft_refine action, refinement_prompt field, _build_refinement_prompt helper, DRAFT_REFINE handling in decision_node, updated get_decision_action
- `src/graph/graph.py` - Updated route_after_decision return type and conditional edges to include draft_refine

## Decisions Made

1. **draft_refine routes to END** - Like other decision actions, draft_refine ends the graph run and the Slack handler processes the result
2. **Refinement prompt varies by draft type** - Epic drafts get "keep/split/add stories" options, other types get "keep/elevate/break down" options
3. **DRAFT_REFINE check before validation** - Added after thread binding check but before approval/reask checks to intercept early

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Phase 26 complete - all 4 plans executed
- Context-aware intent classification with DRAFT_REFINE handling operational
- Ready for phase transition

---
*Phase: 26-context-aware-intent*
*Completed: 2026-01-22*
