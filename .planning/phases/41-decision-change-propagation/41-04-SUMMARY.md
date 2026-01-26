---
phase: 41-decision-change-propagation
plan: 04
subsystem: decision-sync
tags: [executor, jira-sync, slack-ui, truth-first]

# Dependency graph
requires:
  - phase: 41-01
    provides: DecisionChangeOp schema and store
  - phase: 41-02
    provides: ImpactAnalysisService
  - phase: 41-03
    provides: Confirmation UI and handlers

provides:
  - DecisionChangeExecutor for transactional apply
  - Truth-first ordering enforcement (DB -> Slack -> Jira)
  - Result card showing success/failure counts
  - Per-ticket result tracking with retry capability

affects: [decision-buttons, decision-commands]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Truth-first ordering (DB -> Slack -> Jira)
    - Best-effort presentation (Slack failures logged, not raised)
    - Per-ticket result tracking for retry

key-files:
  created:
    - src/sync/decision_change_executor.py
  modified:
    - src/schemas/decision.py
    - src/slack/blocks/decision_cards.py
    - src/slack/handlers/decision_change_handlers.py

key-decisions:
  - "Execute with truth-first ordering: DB first (truth), Slack second (presentation), Jira third (projection)"
  - "Slack failures are logged but don't abort operations - presentation is best effort"
  - "Per-ticket results enable granular retry capability"
  - "Result card shows phase status and failed ticket details"

patterns-established:
  - "DecisionChangeExecutor pattern: confirm -> execute -> result"
  - "ApplyResult tracks three phases independently"

issues-created: []

# Metrics
duration: 12min
completed: 2026-01-26
---

# Phase 41-04: Transactional Apply + Result Card Summary

**DecisionChangeExecutor with truth-first ordering (DB -> Slack -> Jira) and result card UI showing per-ticket outcomes**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-26T10:30:00Z
- **Completed:** 2026-01-26T10:42:00Z
- **Tasks:** 5
- **Files modified:** 4

## Accomplishments

- Created DecisionChangeExecutor with execute() method using truth-first ordering
- ApplyResult and ApplyTicketResult models track per-phase and per-ticket outcomes
- Result card shows success/failure status with retry button for failed tickets
- Handler integration connects confirmation UI to executor with proper error handling
- Retry capability for failed Jira syncs via retry_failed_tickets()

## Task Commits

Each task was committed atomically:

1. **Task 1: ApplyResult Models** - `bf906a2` (feat)
2. **Task 2: DecisionChangeExecutor** - `b704181` (feat)
3. **Task 3: Result Card Builder** - `e7c70fb` (feat)
4. **Task 4+5: Handler Integration** - `ce16f65` (feat)

**Plan metadata:** (included in task commits)

## Files Created/Modified

- `src/schemas/decision.py` - Added ApplyTicketResult and ApplyResult models
- `src/sync/decision_change_executor.py` - NEW: Executor with truth-first ordering
- `src/slack/blocks/decision_cards.py` - Added build_change_result_card function
- `src/slack/handlers/decision_change_handlers.py` - Integrated executor and retry handler

## Decisions Made

- **Truth-first ordering:** DB (truth) must succeed before Slack (presentation) and Jira (projection)
- **Best-effort Slack:** Slack failures are logged but don't abort the operation
- **Per-ticket tracking:** ApplyTicketResult enables granular retry for individual failed tickets
- **Retry button:** Failed tickets can be retried without re-running the entire operation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- DecisionChangeExecutor is ready for use by confirmation handlers
- Result card displays all phases (DB, Slack, Jira) with counts
- Retry button enables recovery from partial failures
- Ready for Plan 41-05: Rollback Support

---
*Phase: 41-decision-change-propagation*
*Completed: 2026-01-26*
