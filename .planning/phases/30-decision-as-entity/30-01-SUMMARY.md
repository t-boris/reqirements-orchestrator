---
phase: 30-decision-as-entity
plan: 01
subsystem: database
tags: [decision, versioning, postgresql, pydantic, crud]

# Dependency graph
requires:
  - phase: 28-structured-draft-evolution
    provides: StructuredDraft schema patterns, DraftLifecycle enum
provides:
  - Decision entity with versioning
  - DecisionStore with CRUD + version history
  - decisions and decision_versions tables
affects: [30-02, 30-03, 30-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Version history pattern: save current state before update"
    - "DecisionStatus state machine: PROPOSED -> APPROVED -> DEPRECATED/REPLACED"

key-files:
  created:
    - src/schemas/decision.py
    - src/db/decision_store.py
  modified:
    - src/db/models.py

key-decisions:
  - "DecisionVersion stores snapshot before each update (immutable history)"
  - "REPLACED status separate from DEPRECATED (tracks replacement chain)"
  - "Canonical message tracking for Slack pinned message pattern"

patterns-established:
  - "Decision versioning: update() saves current to history then increments"
  - "DecisionType enum maps to Jira field locations (ARCH -> Description.Architecture)"

issues-created: []

# Metrics
duration: 3min
completed: 2026-01-24
---

# Phase 30 Plan 01: Decision Entity and DecisionStore Summary

**Decision entity schema with DecisionType/DecisionStatus enums and DecisionStore with versioned CRUD operations**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-24T00:59:58Z
- **Completed:** 2026-01-24T01:02:48Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Created Decision schema with 6 decision types (ARCH, SCOPE, CONSTRAINT, PRIORITY, STRUCTURE, PROCESS)
- Created DecisionStatus lifecycle (PROPOSED, APPROVED, DEPRECATED, REPLACED)
- Created DecisionStore with full CRUD + versioning support
- Implemented version history pattern: every update saves current state before modifying

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Decision schema with enums and versioning** - `a97c76d` (feat)
2. **Task 2: Add Decision model to db/models.py** - `a358e98` (feat)
3. **Task 3: Create DecisionStore with CRUD and versioning** - `ba27198` (feat)

## Files Created/Modified

- `src/schemas/decision.py` - Decision, DecisionType, DecisionStatus, DecisionVersion schemas
- `src/db/models.py` - Re-export Decision models for convenience imports
- `src/db/decision_store.py` - DecisionStore with create_tables, CRUD, approve, deprecate, version history

## Decisions Made

1. **DecisionVersion stores snapshot before each update** - Immutable history enables rollback and audit
2. **REPLACED status separate from DEPRECATED** - Tracks replacement chain (replaced_by field)
3. **Canonical message tracking** - canonical_message_ts and discussion_thread_ts support Slack pinned message pattern

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Decision entity and store ready for use
- Next plan (30-02) can implement DecisionLink for Jira mapping
- Pattern established for version history that can be reused

---
*Phase: 30-decision-as-entity*
*Completed: 2026-01-24*
