---
phase: 20-brain-refactor
plan: 03
subsystem: graph
tags: [event-validation, workflow-step, stale-ui]

# Dependency graph
requires:
  - phase: 20-01
    provides: WorkflowStep enum for mapping allowed events
provides:
  - ALLOWED_EVENTS mapping for event validation per workflow step
  - validate_event() function for stale UI detection
  - validate_ui_version() for preview version checking
affects: [20-05, 20-06]  # Event routing, handler integration

# Tech tracking
tech-stack:
  added: []
  patterns: [event-allowed-set-per-step, ui-version-validation]

key-files:
  created: [src/graph/event_validation.py, tests/test_event_validation.py]
  modified: []

key-decisions:
  - "WorkflowStep -> set[str] mapping for allowed events"
  - "Separate ui_version check for same-step stale detection"
  - "Predefined error messages for consistent UX"

patterns-established:
  - "ALLOWED_EVENTS pattern: each WorkflowStep has explicit allowed actions"
  - "importlib pattern for tests to avoid circular imports"

issues-created: []

# Metrics
duration: 3min
completed: 2026-01-16
---

# Phase 20 Plan 03: Event Validation Summary

**ALLOWED_EVENTS mapping with validate_event() and validate_ui_version() for preventing stale UI button clicks**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-16T00:48:22Z
- **Completed:** 2026-01-16T00:51:10Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created event validation module with ALLOWED_EVENTS mapping covering all 6 WorkflowStep values
- Implemented validate_event() to check if button action is allowed for current workflow step
- Implemented validate_ui_version() to detect stale preview button clicks after edits
- Added 10 unit tests covering all validation scenarios

## Task Commits

Each task was committed atomically:

1. **Task 1: Create event validation module** - `a891534` (feat)
2. **Task 2: Add unit tests for event validation** - `c85022d` (test)

**Plan metadata:** (this commit)

## Files Created/Modified

- `src/graph/event_validation.py` - Event validation logic with ALLOWED_EVENTS, validate_event, validate_ui_version
- `tests/test_event_validation.py` - 10 unit tests covering event validation scenarios

## Decisions Made

- **WorkflowStep -> set[str] mapping**: Each step has explicit set of allowed event actions (approve, edit, etc.)
- **Separate ui_version check**: Validates same-step stale detection (click on old preview after edit)
- **Predefined error messages**: STALE_EVENT_MESSAGE, STALE_VERSION_MESSAGE, ALREADY_PROCESSED_MESSAGE

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Event validation module ready for integration in event routing (Plan 05)
- All WorkflowStep values have entries in ALLOWED_EVENTS
- Tests verify completeness: test_all_steps_have_allowed_events ensures no steps are missed

---
*Phase: 20-brain-refactor*
*Completed: 2026-01-16*
