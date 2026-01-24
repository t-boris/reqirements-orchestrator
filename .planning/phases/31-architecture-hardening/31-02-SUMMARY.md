---
phase: 31-architecture-hardening
plan: 02
subsystem: jira
tags: [validation, invariants, testing, managed-sections]

# Dependency graph
requires:
  - phase: 30-decision-first-class
    provides: Managed sections for Jira description updates
provides:
  - ManagedSectionError exception for invariant violations
  - validate_section_boundaries() validation function
  - verify_user_content_preserved() test helper
  - Comprehensive test suite proving MANAGED_SECTION_ONLY invariant
affects: [decision-sync, jira-projection]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "INVARIANT docstring pattern for critical constraints"
    - "Mock-based testing for circular import avoidance"

key-files:
  created:
    - tests/test_managed_sections.py
  modified:
    - src/jira/managed_sections.py

key-decisions:
  - "Validation rejects nested markers and missing end markers"
  - "verify_user_content_preserved() extracts user content for comparison"
  - "Tests use direct file import to avoid circular import issues"

patterns-established:
  - "INVARIANT docstring: Document critical invariants in function docstrings"
  - "Validation before mutation: Always validate before modifying data"

issues-created: []

# Metrics
duration: 4min
completed: 2026-01-24
---

# Phase 31 Plan 02: Enforce MANAGED_SECTION_ONLY Invariant Summary

**ManagedSectionError exception with validation functions and 18 tests proving user content is NEVER modified outside managed section**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-24T01:59:05Z
- **Completed:** 2026-01-24T02:02:42Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added ManagedSectionError exception for invariant violations
- Implemented validate_section_boundaries() to detect malformed sections (nested markers, missing end)
- Added verify_user_content_preserved() helper for testing
- Created comprehensive test suite with 18 tests proving the invariant
- Documented INVARIANT in update_description_with_managed_section() docstring

## Task Commits

Each task was committed atomically:

1. **Task 1: Add validation to managed section updates** - `15fdfab` (feat)
2. **Task 2: Create comprehensive tests for managed section invariants** - `73dc2c3` (test)

## Files Created/Modified

- `src/jira/managed_sections.py` - Added ManagedSectionError, validate_section_boundaries(), verify_user_content_preserved(), updated docstring with INVARIANT
- `tests/test_managed_sections.py` - 18 comprehensive tests proving MANAGED_SECTION_ONLY invariant

## Decisions Made

- **Validation approach**: Reject nested markers and missing end markers rather than attempting recovery
- **Test isolation**: Use direct file import with mocked dependencies to avoid circular import issues in the codebase
- **Invariant documentation**: State invariant in docstring for clear developer communication

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- MANAGED_SECTION_ONLY invariant is now enforced in code
- Tests prove: user content never modified, malformed sections rejected
- Ready for next plan in Phase 31 (31-03 or 31-04)

---
*Phase: 31-architecture-hardening*
*Completed: 2026-01-24*
