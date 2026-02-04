---
phase: 10-code-review-polish
plan: 03
subsystem: database, projections
tags: [postgresql, alembic, event-sourcing, projections, read-model]

# Dependency graph
requires:
  - phase: 09-decision-lifecycle
    provides: DecisionAmended event with new_adr_message_ts, DecisionRecorded with adr_message_ts
provides:
  - adr_message_ts column on entities_view read model
  - projection consistency for DecisionRecorded and DecisionAmended events
affects: [10-05-adr-lifecycle-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "COALESCE pattern for nullable column updates in projections"
    - "getattr for safe field access on polymorphic events"

key-files:
  created:
    - alembic/versions/003_add_adr_message_ts.py
  modified:
    - src/infrastructure/projections.py

key-decisions:
  - "Approvals NOT reset on amendment — aggregate preserves them by design"
  - "adr_message_ts stored as dedicated column, not in content JSONB"
  - "COALESCE used to preserve existing adr_message_ts when amendment has null new_adr_message_ts"

issues-created: []

# Metrics
duration: 2min
completed: 2026-02-04
---

# Phase 10 Plan 03: Projection Consistency Summary

**Added adr_message_ts column to entities_view and updated DecisionRecorded/DecisionAmended projections to persist ADR message timestamps**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-04T15:27:01Z
- **Completed:** 2026-02-04T15:28:54Z
- **Tasks:** 5
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- Added Alembic migration 003 to add `adr_message_ts` column to `entities_view`
- Updated `_amend_decision_content` to persist `new_adr_message_ts` from `DecisionAmended` events using COALESCE
- Updated `_create_entity` to persist `adr_message_ts` from `DecisionRecorded` events on initial recording
- Documented that approvals are intentionally preserved on amendment (matches aggregate behavior)

## Task Commits

Each task was committed atomically:

1. **Task 1: Read and analyze structure** - Discovery only, no commit
2. **Task 2: Add adr_message_ts column and update amendment projection** - `a379d84` (fix)
3. **Task 3: Handle approval reset on amendment** - No code change, documented decision (aggregate preserves approvals)
4. **Task 4: Update DecisionRecorded projection to store adr_message_ts** - `c96f514` (fix)
5. **Task 5: Run tests** - All 29 tests pass (20 passed, 9 skipped for no DB)

## Files Created/Modified
- `alembic/versions/003_add_adr_message_ts.py` - Migration adding adr_message_ts column to entities_view
- `src/infrastructure/projections.py` - Updated _create_entity and _amend_decision_content to persist adr_message_ts

## Decisions Made
- **Approvals NOT reset on amendment:** The aggregate (`channel.py` `amend_decision`) explicitly preserves `approvals=entity.approvals` for ProposedEntity amendments. The projection mirrors this behavior. If approval reset is added to the domain layer in the future, the projection should be updated accordingly.
- **Dedicated column vs JSONB:** Stored `adr_message_ts` as a dedicated VARCHAR(50) column rather than in the content JSONB blob, for cleaner querying and consistency with `canonical_message_ts` which follows the same pattern.
- **COALESCE for null safety:** Used `COALESCE($3, adr_message_ts)` in the amendment UPDATE so that amendments without a new ADR message preserve the existing value.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness
- ISS-008 closed
- Read model now accurately reflects adr_message_ts after recording and amendment
- Ready for 10-04 (Async Jira notifications) or other wave 2/3 plans

---
*Phase: 10-code-review-polish*
*Completed: 2026-02-04*
