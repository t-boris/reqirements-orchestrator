---
phase: 09-decision-lifecycle
plan: 02
subsystem: jira
tags: [jira, notifications, deprecation, amendment, decisions]

# Dependency graph
requires:
  - phase: 06-jira-projection
    provides: JiraSyncService with project_decision and reconcile methods
provides:
  - notify_decision_deprecated() for posting supersession comments to Jira
  - notify_decision_amended() for posting amendment comments to Jira
affects: [09-03, 09-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [fault-tolerant Jira notifications with log-and-continue error handling]

key-files:
  created: []
  modified: [src/jira/sync_service.py]

key-decisions:
  - "Both notification methods are fault-tolerant: log warning on Jira errors, never propagate exceptions"
  - "Used _Updated via MARO_ footer (consistent with existing _Recorded via MARO_ in decision comments)"

patterns-established:
  - "Fault-tolerant notification pattern: try/except around Jira calls with logger.warning on failure"

issues-created: []

# Metrics
duration: 1min
completed: 2026-02-04
---

# Phase 9 Plan 2: Jira Decision Notifications Summary

**Fault-tolerant Jira notifications for decision deprecation and amendment via JiraSyncService**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-04T14:32:21Z
- **Completed:** 2026-02-04T14:33:11Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Added `notify_decision_deprecated()` method that posts supersession comment to linked Jira issue
- Added `notify_decision_amended()` method that posts amendment comment with old/new content diff
- Both methods handle missing jira_link (return silently) and Jira API errors (log warning, no exception)
- Added `_format_deprecation_comment()` and `_format_amendment_comment()` formatting helpers

## Task Commits

Each task was committed atomically:

1. **Task 1: Add deprecation and amendment notification methods** - `13b0533` (feat)

## Files Created/Modified
- `src/jira/sync_service.py` - Added notify_decision_deprecated(), notify_decision_amended(), and formatting helpers

## Decisions Made
- Both notification methods use fault-tolerant pattern (try/except with log warning) to ensure decision operations succeed even when Jira is unreachable
- Used "_Updated via MARO_" footer to distinguish lifecycle notifications from initial recording comments which use "_Recorded via MARO_"

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Jira notification methods ready for integration with Slack handlers in 09-03 and 09-04
- notify_decision_deprecated() can be called from deprecation UI flow
- notify_decision_amended() can be called from amendment detection handlers

---
*Phase: 09-decision-lifecycle*
*Completed: 2026-02-04*
