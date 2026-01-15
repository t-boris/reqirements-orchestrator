---
phase: 13-intent-router
plan: 04
subsystem: graph
tags: [intent-classification, testing, pytest, scope-gate, review-to-ticket]

# Dependency graph
requires:
  - phase: 13-02
    provides: Review flow with persona-based analysis
  - phase: 13-03
    provides: Discussion flow with brief responses
provides:
  - Review-to-ticket transition with scope gate UI
  - classify_intent_patterns exported for testing
  - Regression test suite for intent classification (53 tests)
affects: [future-test-expansion, intent-refactoring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Direct module loading with importlib to avoid circular imports in tests"
    - "Scope gate modal for user choice before flow transition"

key-files:
  created:
    - tests/__init__.py
    - tests/test_intent_router.py
  modified:
    - src/slack/handlers.py
    - src/slack/router.py
    - src/graph/intent.py

key-decisions:
  - "Scope gate offers 3 options: decision only, full review, or custom description"
  - "Modal submission posts context message to trigger ticket flow"
  - "Tests use importlib to load intent.py directly, avoiding circular imports"

patterns-established:
  - "Flow transition pattern: button -> modal -> context message -> flow trigger"
  - "Test isolation: Direct module loading bypasses __init__.py import chains"

issues-created: []

# Metrics
duration: 15min
completed: 2026-01-15
---

# Phase 13 Plan 04: Scope Gate + Intent Tests Summary

**Review-to-ticket transition with scope selection modal, plus 53-test regression suite for intent classification patterns**

## Performance

- **Duration:** 15 min
- **Started:** 2026-01-15T17:21:00Z
- **Completed:** 2026-01-15T17:36:43Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Review responses now include "Turn into Jira ticket" button
- Scope gate modal lets users choose: decision only, full review, or custom
- Modal submission triggers ticket flow with selected scope context
- classify_intent_patterns exported as public function for testing
- 53 regression tests covering TICKET, REVIEW, DISCUSSION patterns
- Tests validate negation priority, persona hints, and confidence scores

## Task Commits

Each task was committed atomically:

1. **Task 1: Add "Turn into ticket" button to review responses** - `bea1c68` (feat)
2. **Task 3: Export classify_intent_patterns for testing** - `27684f0` (refactor)
3. **Task 2: Create regression test suite for intent classification** - `b5b6b4b` (test)

## Files Created/Modified

- `src/slack/handlers.py` - Review action now uses blocks with button, added handle_review_to_ticket and handle_scope_gate_submit
- `src/slack/router.py` - Registered new action and view handlers
- `src/graph/intent.py` - Renamed _check_patterns to classify_intent_patterns (public)
- `tests/__init__.py` - Created test package
- `tests/test_intent_router.py` - 53 regression tests for pattern classification

## Decisions Made

1. **Scope gate options** - Three choices: "Final decision only", "Full review/proposal", "Specific part (I'll describe)". Full review is the default.

2. **Modal-to-flow trigger** - Scope gate submission posts a context message that triggers the normal message handler, which will classify as TICKET and proceed with extraction.

3. **Test isolation approach** - Used importlib to load intent.py directly instead of importing through src.graph package, avoiding circular import issues that exist in the codebase.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Circular import in test module**
- **Found during:** Task 2 (Test suite creation)
- **Issue:** Importing from src.graph.intent triggered circular imports through src.graph.__init__.py
- **Fix:** Used importlib.util to load intent.py directly from file path
- **Files modified:** tests/test_intent_router.py
- **Verification:** Tests collect and run successfully (53 passed)
- **Committed in:** b5b6b4b

---

**Total deviations:** 1 auto-fixed (blocking circular import issue)
**Impact on plan:** Necessary workaround for existing codebase structure. No scope creep.

## Issues Encountered

None - all tasks completed successfully after addressing the circular import.

## Next Phase Readiness

- Phase 13: Intent Router is COMPLETE
- All 4 plans executed (01-04)
- Intent classification, Review flow, Discussion flow, and Scope gate all operational
- Regression tests ensure pattern classification reliability
- Ready for next milestone

---
*Phase: 13-intent-router*
*Completed: 2026-01-15*
