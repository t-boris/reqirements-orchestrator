---
phase: 20-brain-refactor
plan: 06
subsystem: intent
tags: [intent-classification, scope-gate, slack-blocks, user-choice]

# Dependency graph
requires:
  - phase: 20-04
    provides: AgentState workflow fields (thread_default_intent, thread_default_expires_at)
  - phase: 20-05
    provides: Event router with routing decision structure
provides:
  - AMBIGUOUS intent type in IntentType enum
  - Scope gate blocks for 3-button user choice UI
  - Scope gate handlers for Review/Ticket/Dismiss actions
  - "Remember for this thread" checkbox functionality
affects: [20-07+, event-routing, intent-to-workflow]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "3-button scope gate for ambiguous intent resolution"
    - "Remember checkbox for thread-level intent preferences"
    - "Handlers separate from blocks for clean responsibility split"

key-files:
  created:
    - src/slack/blocks/scope_gate.py
    - src/slack/handlers/scope_gate.py
  modified:
    - src/graph/intent.py
    - src/slack/blocks/__init__.py
    - src/slack/handlers/__init__.py

key-decisions:
  - "Remove 'lean toward TICKET' bias from LLM classification"
  - "AMBIGUOUS triggers scope gate instead of guessing"
  - "3 buttons: Review / Create Ticket / Not now"
  - "Remember checkbox stores thread default with 2h expiry"

patterns-established:
  - "User decides intent when bot is unsure (no guessing)"
  - "Thread-level preferences reduce repeated scope gates"

issues-created: []

# Metrics
duration: 3min
completed: 2026-01-16
---

# Phase 20 Plan 06: Scope Gate for AMBIGUOUS Intent Summary

**AMBIGUOUS intent type added with 3-button scope gate UI, removing "lean toward TICKET" bias so user decides when intent is unclear**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-16T00:58:38Z
- **Completed:** 2026-01-16T01:02:00Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Added AMBIGUOUS to IntentType enum for unclear user intent
- Removed "lean toward TICKET" bias from LLM classification prompt
- Created scope gate blocks with 3 buttons + remember checkbox
- Created scope gate handlers for review/ticket/dismiss actions
- All 168 tests pass with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Update intent classification to include AMBIGUOUS** - `4677a0a` (feat)
2. **Task 2: Create scope gate blocks** - `1ed1dd7` (feat)
3. **Task 3: Create scope gate handlers** - `5022efc` (feat)

## Files Created/Modified

- `src/graph/intent.py` - Added AMBIGUOUS to IntentType, updated LLM prompt to remove TICKET bias
- `src/slack/blocks/scope_gate.py` - New file with build_scope_gate_blocks(), dismissed, remembered block builders
- `src/slack/handlers/scope_gate.py` - New file with handle_scope_gate_review/ticket/dismiss handlers
- `src/slack/blocks/__init__.py` - Export scope gate block builders
- `src/slack/handlers/__init__.py` - Export scope gate handlers

## Decisions Made

1. **Remove "lean toward TICKET" bias** - LLM now chooses AMBIGUOUS when intent is unclear instead of defaulting to TICKET
2. **3-button scope gate design** - Review / Create Ticket / Not now gives user clear choices
3. **"Remember for this thread" checkbox** - Reduces repeated scope gates in same thread
4. **2h expiry for thread default** - Aligns with 20-CONTEXT.md v4 requirements
5. **Handlers separate from blocks** - Clean responsibility split following existing codebase patterns

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- AMBIGUOUS intent type ready for integration with event router (20-05)
- Scope gate blocks ready to be displayed when AMBIGUOUS is classified
- Handlers ready to process user choices and update thread_default_intent
- Thread default expiry ready to be enforced by state management (already in AgentState from 20-04)

---
*Phase: 20-brain-refactor*
*Completed: 2026-01-16*
