---
phase: 20-brain-refactor
plan: 11
subsystem: database
tags: [postgresql, fact-store, context-persistence, eviction, dedup]

# Dependency graph
requires:
  - phase: 20-01
    provides: State types (enums, TypedDicts)
provides:
  - Fact TypedDict for structured salient facts
  - FactStore with UPSERT and eviction
  - compute_canonical_id for fact deduplication
affects: [context-loading, fact-extraction, memory-management]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Canonical ID deduplication via SHA256 hash
    - Eviction by confidence ranking (lowest first)
    - UPSERT pattern for merge instead of append

key-files:
  created:
    - src/db/fact_store.py
    - tests/test_fact_store.py
  modified:
    - src/schemas/state.py
    - src/db/__init__.py

key-decisions:
  - "Use psycopg (not asyncpg) for consistency with existing codebase"
  - "UPSERT uses GREATEST() to keep highest confidence on merge"
  - "Canonical ID is 16-char hex for compact storage"

patterns-established:
  - "Fact dedup: hash(text.lower().strip() + scope + type)"
  - "Eviction: lowest confidence first, then oldest"

issues-created: []

# Metrics
duration: 8min
completed: 2026-01-16
---

# Phase 20 Plan 11: Salient Facts Summary

**Structured salient_facts with Fact TypedDict for context persistence and FactStore with UPSERT/eviction**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-16T01:10:00Z
- **Completed:** 2026-01-16T01:18:49Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Fact TypedDict with 6 fields: type, scope, source_ts, text, confidence, canonical_id
- FACT_LIMITS for eviction thresholds: thread=50, epic=200, channel=300
- FactStore with add_fact (UPSERT), get_facts, ensure_table, _evict_if_needed
- compute_canonical_id for fact deduplication via SHA256 hash
- salient_facts field added to AgentState

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Fact TypedDict to state.py** - `d56b59a` (feat)
2. **Task 2: Create FactStore with eviction** - `6d59cb8` (feat)
3. **Task 3: Export from db package and add tests** - `f883034` (feat)

## Files Created/Modified

- `src/schemas/state.py` - Added Fact TypedDict, FACT_LIMITS, salient_facts in AgentState
- `src/db/fact_store.py` - New FactStore class with UPSERT and eviction
- `src/db/__init__.py` - Export FactStore and compute_canonical_id
- `tests/test_fact_store.py` - 8 unit tests for canonical ID computation

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Use psycopg (not asyncpg) | Consistent with existing codebase pattern |
| UPSERT with GREATEST(confidence) | Keep highest confidence on merge for dedup |
| 16-char hex canonical ID | Compact storage, sufficient uniqueness |
| Evict by confidence ASC, updated_at ASC | Remove lowest value facts first |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Changed asyncpg to psycopg**
- **Found during:** Task 2 (Create FactStore)
- **Issue:** Plan template used asyncpg.Connection but codebase uses psycopg.AsyncConnection
- **Fix:** Changed import and SQL placeholder syntax (%s instead of $N)
- **Files modified:** src/db/fact_store.py
- **Verification:** Import succeeds, syntax consistent with other stores
- **Committed in:** 6d59cb8 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (blocking)
**Impact on plan:** Library alignment for consistency. No scope creep.

## Issues Encountered

None - plan executed smoothly after adapting to codebase conventions.

## Next Phase Readiness

- FactStore ready for integration in context loading nodes
- Fact TypedDict ready for use in fact extraction
- Eviction policy will maintain bounded fact counts per scope
- Next: Plan 12 (final plan of Phase 20)

---
*Phase: 20-brain-refactor*
*Completed: 2026-01-16*
