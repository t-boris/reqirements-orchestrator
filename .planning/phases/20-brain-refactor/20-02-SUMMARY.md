---
phase: 20-brain-refactor
plan: 02
subsystem: database
tags: [postgres, idempotency, event-tracking, psycopg]

# Dependency graph
requires:
  - phase: 20-brain-refactor
    provides: state.py foundation for event types
provides:
  - EventStore class for processed_event_ids tracking
  - make_button_event_id helper for button click fallback keys
affects: [20-03 (event routing), handler idempotency integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [INSERT ON CONFLICT for race-safe deduplication]

key-files:
  created: [src/db/event_store.py]
  modified: [src/db/__init__.py]

key-decisions:
  - "Use psycopg v3 (not asyncpg) to match existing db module pattern"
  - "24h TTL for event cleanup - balance between dedup window and storage"
  - "INSERT ON CONFLICT DO NOTHING for race-safe marking"

patterns-established:
  - "EventStore follows ListeningStore pattern (conn in constructor)"

issues-created: []

# Metrics
duration: 4min
completed: 2026-01-15
---

# Phase 20 Plan 02: Event Store Summary

**PostgreSQL-backed event store for idempotency tracking with 24h TTL and race-safe INSERT ON CONFLICT**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-15T00:00:00Z
- **Completed:** 2026-01-15T00:04:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created EventStore class with PostgreSQL-backed storage for processed event IDs
- Implemented race-safe marking with INSERT ON CONFLICT DO NOTHING
- Added 24h TTL cleanup method for event maintenance
- Exported EventStore and make_button_event_id from src.db package

## Task Commits

Each task was committed atomically:

1. **Task 1: Create EventStore class** - `2657dc8` (feat)
2. **Task 2: Export from db package** - `030ee2e` (feat)

## Files Created/Modified
- `src/db/event_store.py` - EventStore class with is_processed, mark_processed, cleanup_old_events, ensure_table methods
- `src/db/__init__.py` - Added EventStore and make_button_event_id exports

## Decisions Made
- **psycopg v3 instead of asyncpg**: Plan referenced asyncpg but project uses psycopg v3. Adapted code to follow existing ListeningStore pattern with cursor-based queries.
- **24h TTL for cleanup**: Default EVENT_TTL_HOURS = 24, sufficient for catching retries/duplicates while keeping storage bounded.
- **Composite key (team_id, event_id)**: Enables multi-workspace support in HA deployment.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Adapted asyncpg API to psycopg v3**
- **Found during:** Task 1 (Create EventStore class)
- **Issue:** Plan code used asyncpg's `conn.fetchval()` and `conn.execute()` API, but project uses psycopg v3 with cursor-based pattern
- **Fix:** Rewrote all methods to use `async with self._conn.cursor() as cur:` pattern matching ListeningStore
- **Files modified:** src/db/event_store.py
- **Verification:** Import test passes, methods have correct signatures
- **Committed in:** 2657dc8 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (blocking - API compatibility)
**Impact on plan:** Essential for code to work. Matches project conventions.

## Issues Encountered
None

## Next Phase Readiness
- EventStore ready for integration in Wave 2 (event routing)
- Plan 20-03 can use EventStore for duplicate event detection

---
*Phase: 20-brain-refactor*
*Completed: 2026-01-15*
