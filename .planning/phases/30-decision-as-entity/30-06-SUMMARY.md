---
phase: 30-decision-as-entity
plan: 06
subsystem: sync
tags: [jira, preflight, managed-sections, conflict-detection]

# Dependency graph
requires:
  - phase: 30-01
    provides: Decision entity and DecisionStore
  - phase: 30-02
    provides: DecisionLink table for decision-to-Jira mappings
provides:
  - Managed sections for safe Jira description updates
  - DecisionPreflightService for decision sync conflict detection
  - get_link() method for preflight lookups
affects: [30-07, 30-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Managed sections: MARO writes only to marked sections, preserves user content"
    - "Decision preflight: Same conflict types as regular sync (no privileges)"

key-files:
  created:
    - src/jira/managed_sections.py
    - src/sync/decision_preflight.py
  modified:
    - src/db/decision_link_store.py

key-decisions:
  - "SECTION_START/SECTION_END markers for MARO-owned content"
  - "Decisions use same 4-type conflict classification as regular preflight"
  - "New links treated as SAFE_DRIFT with can_proceed=True"

patterns-established:
  - "Managed sections: ## Decisions (managed by MARO) ... ---"
  - "extract/render/update pattern for safe section manipulation"

issues-created: []

# Metrics
duration: 2min
completed: 2026-01-24
---

# Phase 30 Plan 06: Decision Preflight Summary

**Managed sections for Jira descriptions with DecisionPreflightService implementing same conflict rules as regular sync**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-24T01:13:18Z
- **Completed:** 2026-01-24T01:15:25Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Created managed_sections.py for safe Jira description updates (MARO writes only to marked sections)
- Created DecisionPreflightService with check_sync() and check_batch_sync()
- Added get_link() method to DecisionLinkStore for preflight lookups
- Decisions don't get "privileges" - same 4-type conflict classification as regular sync

## Task Commits

Each task was committed atomically:

1. **Task 1: Create managed sections renderer** - `30fb3a9` (feat)
2. **Task 2: Create DecisionPreflightService** - `0048149` (feat)
3. **Task 3: Add get_link method to DecisionLinkStore** - `f331763` (feat)

## Files Created/Modified

- `src/jira/managed_sections.py` - Managed sections for safe Jira description updates
  - SECTION_START/SECTION_END markers for MARO-owned content
  - extract_managed_section() - finds existing managed block
  - render_managed_section() - formats decisions list
  - update_description_with_managed_section() - preserves user content
- `src/sync/decision_preflight.py` - Preflight service for decision sync
  - DecisionPreflightResult dataclass with conflict classification
  - check_sync() - preflight for single decision-ticket pair
  - check_batch_sync() - preflight all linked tickets
- `src/db/decision_link_store.py` - Added get_link() method
  - Returns specific link between decision and ticket for preflight

## Decisions Made

- **Managed section markers:** `## Decisions (managed by MARO)` as start, `---` as end
- **Conflict types:** IDEMPOTENT, SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL (same as regular preflight)
- **New links:** Treated as SAFE_DRIFT with can_proceed=True (no prior state to conflict with)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Managed sections ready for Jira description updates
- DecisionPreflightService ready for decision approval flow
- Preflight integrates with existing ConflictType from src/sync/preflight.py
- Ready for 30-07: Graph routing for DECISION intent

---
*Phase: 30-decision-as-entity*
*Completed: 2026-01-24*
