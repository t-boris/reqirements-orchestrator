---
phase: 29-sync-on-demand
plan: 01
subsystem: database
tags: [jira, sync, registry, psycopg]

# Dependency graph
requires:
  - phase: 23.1
    provides: JiraRegistryStore foundation
provides:
  - JiraIssueLink with sync tracking fields (status, assignee, jira_updated, last_synced)
  - update_from_jira() method for Jira API sync
  - get_stale_issues() method for finding issues needing sync
  - mark_deleted() method for externally deleted issues
affects: [29-preflight-sync, 29-maro-sync]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - COALESCE for optional field preservation in UPSERT
    - Backward-compatible row parsing with len() checks
    - Staleness detection with NULL handling (NULLS FIRST)

key-files:
  created: []
  modified:
    - src/db/jira_registry.py

key-decisions:
  - "Use COALESCE pattern in register() to preserve existing data when new values None"
  - "Set last_synced = now() only when sync fields are provided"
  - "mark_deleted() sets status to DELETED_EXTERNALLY rather than removing record"
  - "get_stale_issues() returns NULLs first (never synced = most stale)"

patterns-established:
  - "Sync tracking pattern: jira_updated (from API) vs last_synced (our fetch time)"

issues-created: []

# Metrics
duration: 3min
completed: 2026-01-23
---

# Phase 29 Plan 01: Enhance JiraRegistryStore with Sync Tracking Summary

**JiraIssueLink enhanced with status/assignee/jira_updated/last_synced fields and three sync methods for Preflight Sync and /maro sync foundation**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-23T23:56:32Z
- **Completed:** 2026-01-23T23:59:31Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments

- Enhanced JiraIssueLink dataclass with 4 new sync tracking fields
- Added 3 new methods: update_from_jira(), get_stale_issues(), mark_deleted()
- Extended register() to accept sync fields with COALESCE preservation
- DB migrations for new columns (backward compatible)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add sync tracking fields to JiraIssueLink** - `3fc1468` (feat)
2. **Task 2: Add sync update methods to JiraRegistryStore** - `2f82c14` (feat)
3. **Task 3: Update register() to accept sync fields** - `3057e76` (feat)

**Plan metadata:** pending (docs: complete plan)

## Files Created/Modified

- `src/db/jira_registry.py` - Enhanced JiraIssueLink dataclass and JiraRegistryStore with sync tracking

## Decisions Made

1. **COALESCE for sync fields** - preserve existing data when new values are None, same pattern as existing fields
2. **last_synced set conditionally** - only set when sync fields are provided, avoids false "synced" state
3. **DELETED_EXTERNALLY status** - mark_deleted() uses special status rather than removing from registry (preserves history)
4. **NULL ordering in get_stale_issues()** - NULLS FIRST ensures never-synced issues are returned first

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Registry now has all fields needed for Preflight Sync conflict detection
- get_stale_issues() ready for /maro sync to find outdated issues
- update_from_jira() ready to receive fresh Jira API data
- Ready for 29-02-PLAN.md (Preflight Sync or /maro sync implementation)

---
*Phase: 29-sync-on-demand*
*Completed: 2026-01-23*
