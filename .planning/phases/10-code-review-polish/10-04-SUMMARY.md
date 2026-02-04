---
phase: 10-code-review-polish
plan: 04
subsystem: infra
tags: [jira, outbox, projections, event-driven, async]

# Dependency graph
requires:
  - phase: 10-01
    provides: Fixed action_id patterns and JSON values in action handlers
provides:
  - Event-driven Jira notification projection (DecisionDeprecated + DecisionAmended)
  - Inline outbox processing in save_events
affects: [10-05-adr-lifecycle]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Side-effect projection: JiraNotificationProjection for async Jira comments"
    - "Inline outbox processing in save_events (no background worker needed)"

key-files:
  created: []
  modified:
    - src/infrastructure/projections.py
    - src/infrastructure/aggregate_loader.py
    - src/slack/handlers/actions.py

key-decisions:
  - "Option B: new JiraNotificationProjection instead of adding to EntityProjection — cleaner separation of read model vs side effects"
  - "Inline outbox processing in save_events rather than background worker — simpler, events processed immediately"
  - "Projection formats Jira comments directly instead of constructing full entity objects — avoids complex entity reconstruction from DB"

patterns-established:
  - "Side-effect projections: external API calls handled by dedicated projections with full fault tolerance"

issues-created: []

# Metrics
duration: 4min
completed: 2026-02-04
---

# Phase 10 Plan 04: Async Jira Notifications Summary

**Decoupled Jira notifications from Slack action handlers into event-driven JiraNotificationProjection via outbox pattern**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-04T15:33:46Z
- **Completed:** 2026-02-04T15:37:14Z
- **Tasks:** 5
- **Files modified:** 3

## Accomplishments
- Removed synchronous Jira API call from `handle_deprecate_confirm` handler
- Created JiraNotificationProjection that handles DecisionDeprecated and DecisionAmended events asynchronously
- Wired inline outbox processing into `save_events` flow — both EntityProjection and JiraNotificationProjection now process events after persistence
- All Jira failures are caught and logged without blocking user interaction or event processing

## Task Commits

Each task was committed atomically:

1. **Task 1: Understand current outbox/projection flow** - analysis only (no commit)
2. **Task 2: Remove Jira calls from action handlers** - `d1ea1ae` (refactor)
3. **Task 3: Add JiraNotificationProjection and wire outbox** - `038aa1e` (feat)
4. **Task 4: Ensure fault tolerance** - verification only (no commit)
5. **Task 5: Run tests** - verification only (no commit)

## Files Created/Modified
- `src/slack/handlers/actions.py` - Removed synchronous Jira notification from handle_deprecate_confirm
- `src/infrastructure/projections.py` - Added JiraNotificationProjection class with fault-tolerant Jira comment posting
- `src/infrastructure/aggregate_loader.py` - Added inline outbox processing via _process_outbox after save_events

## Decisions Made
- **New projection over extending EntityProjection**: JiraNotificationProjection is a separate class because EntityProjection is purely for the entities_view read model. Mixing side effects (Jira API calls) into the read model projection would violate single responsibility.
- **Inline outbox processing over background worker**: The outbox processor was defined but never started as a background task. Rather than adding startup complexity, save_events now calls `_process_outbox` inline after persisting. Events are processed immediately, and any failure is caught without blocking the save flow.
- **Direct comment formatting over entity reconstruction**: The projection formats Jira comments directly from event data and DB lookups, rather than constructing full DeprecatedEntity/AmendedEntity objects. This avoids the complexity of reconstructing domain entities from the read model.

## Deviations from Plan

### Observations

**1. handle_record_confirm (amend branch) had no Jira call to remove**

- **Found during:** Task 2 (Remove Jira calls from action handlers)
- **Issue:** The plan expected `sync_service.notify_decision_amended()` to be present in the amend branch, but it was never added
- **Resolution:** No removal needed — the JiraNotificationProjection handles this case via the DecisionAmended event in the outbox
- **Impact:** None — the projection covers both event types regardless of whether they were previously handled inline

**2. Outbox processor not wired up in production**

- **Found during:** Task 1 (Architecture analysis)
- **Issue:** OutboxProcessor exists but was never started as a background worker — projections were not being consumed
- **Resolution:** Added inline outbox processing in save_events, which processes events immediately after persistence
- **Impact:** Both EntityProjection and JiraNotificationProjection now run on every save_events call

---

**Total deviations:** 0 auto-fixed, 0 deferred
**Impact on plan:** No scope changes. All objectives met.

## Issues Encountered
None

## Next Phase Readiness
- Jira notifications fully decoupled from action handlers
- Action handlers complete within Slack's 3s window regardless of Jira status
- Ready for 10-05 (ADR lifecycle UI on pinned messages)
- ISS-005 can be closed

---
*Phase: 10-code-review-polish*
*Completed: 2026-02-04*
