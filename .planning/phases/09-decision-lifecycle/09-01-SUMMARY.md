---
phase: 09-decision-lifecycle
plan: 01
subsystem: domain
tags: [event-sourcing, decision-lifecycle, pydantic, aggregate]

# Dependency graph
requires:
  - phase: 04-entity-lifecycle
    provides: Entity sum types, ChannelAggregate, transitions
provides:
  - DecisionAmended domain event with audit trail
  - ChannelAggregate.amend_decision() for Draft and Proposed entities
  - Event replay support for DecisionAmended
  - Projection handler for DecisionAmended
affects: [09-03, 09-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [content-snapshot-for-audit, frozen-entity-reconstruction]

key-files:
  modified:
    - src/domain/events.py
    - src/domain/channel.py
    - src/infrastructure/projections.py

key-decisions:
  - "Approvals/objections NOT cleared on amendment - social contract, not technical"
  - "Content serialized via model_dump() to match existing event pattern (DecisionContent alias is dict in events.py)"

patterns-established:
  - "Amendment pattern: snapshot previous content, create new frozen entity, emit event with both versions"

issues-created: []

# Metrics
duration: 3min
completed: 2026-02-04
---

# Phase 9 Plan 1: Decision Amendment Domain Layer Summary

**DecisionAmended event with previous/new content audit trail, amend_decision() aggregate method for Draft and Proposed entities, projection handler for entities_view updates**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-04T14:32:21Z
- **Completed:** 2026-02-04T14:35:07Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added DecisionAmended event with previous_content snapshot for full audit trail
- Implemented amend_decision() on ChannelAggregate supporting both Draft and Proposed entities
- Added _apply_event handler for DecisionAmended enabling aggregate rebuild from events
- Wired DecisionAmended into EntityProjection for entities_view content/version updates

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DecisionAmended event and amend_decision method** - `e4722f7` (feat)
2. **Task 2: Wire DecisionAmended into projections** - `7bbb21a` (feat)
3. **Bug fix: serialize content with model_dump()** - `2846cd8` (fix)

## Files Created/Modified
- `src/domain/events.py` - Added DecisionAmended event class with previous_content, new_content, reason, new_adr_message_ts fields; added to _CORE_EVENT_TYPES registry
- `src/domain/channel.py` - Added amend_decision() method, DecisionAmended _apply_event case, imported DecisionAmended and can_modify
- `src/infrastructure/projections.py` - Added DecisionAmended handler to EntityProjection, updates content and version in entities_view

## Decisions Made
- Approvals and objections are NOT cleared on amendment -- if the team has already approved, amending rationale/alternatives should not reset votes. Substantial content changes are a social contract, not a technical one.
- Content fields are serialized via model_dump() before passing to DecisionAmended event, matching the existing pattern used by DecisionRecorded (since DecisionContent in events.py is a dict alias).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed content serialization in amend_decision**
- **Found during:** Task 1 verification
- **Issue:** DecisionContent Pydantic models passed directly to DecisionAmended event constructor, but events.py defines DecisionContent as dict[str, Any] alias -- Pydantic validation rejected the model instances
- **Fix:** Called model_dump() on previous_content and new_content before passing to event constructor
- **Files modified:** src/domain/channel.py
- **Verification:** Full functional test passes -- Draft and Proposed amendment, event serialization, aggregate replay
- **Committed in:** 2846cd8

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential fix for correct operation. No scope creep.

## Issues Encountered
None

## Next Phase Readiness
- DecisionAmended event is registered in _CORE_EVENT_TYPES and will deserialize correctly from event store
- amend_decision() is ready for use by RECORD mode handlers (09-03)
- Projection updates entities_view, so dashboard queries will reflect amendments
- Ready for 09-03 (RECORD mode amendment detection)

---
*Phase: 09-decision-lifecycle*
*Completed: 2026-02-04*
