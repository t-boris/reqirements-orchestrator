---
phase: 09-decision-lifecycle
plan: 04
subsystem: slack-handlers
tags: [slack, deprecation, dashboard, jira-notifications, action-handlers]

# Dependency graph
requires:
  - phase: 09-decision-lifecycle
    provides: deprecate_decision() method, DecisionDeprecated event, JiraSyncService.notify_decision_deprecated(), get_lifecycle helper
provides:
  - Deprecation UI flow from Slack (button -> confirm -> deprecate -> Jira -> dashboard)
  - Dashboard with decision lifecycle status indicators (active/committed/deprecated)
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: [confirmation-flow-for-destructive-actions, factory-based-service-instantiation]

key-files:
  modified:
    - src/slack/handlers/actions.py
    - src/slack/blocks/builders.py

key-decisions:
  - "Use get_sync_service() factory from src/jira/factory.py for Jira integration -- avoids hard-coding credentials"
  - "Deprecation is only allowed on CommittedEntity -- enforced at handler level before showing confirmation"
  - "Dashboard shows max 5 active + 2 deprecated decisions to respect Slack block limits"

patterns-established:
  - "Destructive action pattern: button -> confirmation message with danger-styled confirm + cancel -> execute or revert"
  - "Dashboard status rendering: checkmark for committed, strikethrough for deprecated, plain for draft/proposed"

issues-created: []

# Metrics
duration: 3min
completed: 2026-02-04
---

# Phase 9 Plan 4: Deprecation UI + Dashboard Enhancement Summary

**Slack deprecation flow with confirmation, Jira notification, ADR marking, and dashboard lifecycle status indicators (active/committed/deprecated counts with visual styling)**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-04T14:41:50Z
- **Completed:** 2026-02-04T14:44:04Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added full deprecation flow: deprecate button on committed decisions triggers confirmation, then deprecates via aggregate, notifies Jira, updates pinned ADR message, and refreshes dashboard
- Dashboard now shows decision lifecycle status with visual indicators: checkmark for committed, strikethrough for deprecated, plain for draft/proposed
- Section header shows active vs deprecated counts separately
- Jira integration uses existing factory pattern (get_sync_service()) -- no hard-coded credentials

## Task Commits

Each task was committed atomically:

1. **Task 1: Add deprecate_decision action handler with Jira notification** - `262fe43` (feat)
2. **Task 2: Enhance dashboard with decision lifecycle status** - `458fc4a` (feat)

## Files Created/Modified
- `src/slack/handlers/actions.py` - Added DEPRECATE_DECISION_PATTERN, DEPRECATE_CONFIRM_PATTERN, handle_deprecate_decision (confirmation prompt), handle_deprecate_confirm (deprecation + Jira + ADR + dashboard); enhanced _update_dashboard_after_decision to include lifecycle status and superseded_by in decision_items; imported CommittedEntity and DeprecatedEntity
- `src/slack/blocks/builders.py` - Updated build_dashboard_blocks decision rendering: active/deprecated count header, checkmark for committed, strikethrough for deprecated, max 5 active + 2 deprecated

## Decisions Made
- Used get_sync_service() factory from src/jira/factory.py for instantiating JiraSyncService in action handlers -- follows existing pattern, avoids hard-coding credentials
- Deprecation only allowed on CommittedEntity -- handler checks type before showing confirmation to prevent invalid state transitions
- Dashboard respects Slack block limits: shows max 5 active decisions + max 2 deprecated decisions

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Phase 9 (Decision Lifecycle) is now complete with all 4 plans executed
- Full decision lifecycle: record -> amend -> deprecate with Jira notifications at each step
- Dashboard reflects decision status in real-time
- All 20 existing tests pass

---
*Phase: 09-decision-lifecycle*
*Completed: 2026-02-04*
