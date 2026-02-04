---
phase: 10-code-review-polish
plan: 05
subsystem: ui
tags: [slack, block-kit, lifecycle, adr, buttons, chat-update]

# Dependency graph
requires:
  - phase: 10-01
    provides: Fixed action_id patterns and JSON value data flow
  - phase: 10-04
    provides: Async Jira notifications via projection
provides:
  - Status badges on pinned ADR messages (Draft/Proposed/Approved/Committed/Deprecated)
  - Lifecycle action buttons on pinned ADR messages
  - Auto-updating pinned messages on every lifecycle transition
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pinned message lifecycle sync via _update_adr_pinned_message helper"
    - "Status badge mapping (STATUS_BADGES) for visual lifecycle state"

key-files:
  created: []
  modified:
    - src/slack/blocks/decisions.py
    - src/slack/handlers/actions.py

key-decisions:
  - "Lifecycle buttons use fixed action_ids (adr_propose, adr_approve, adr_object, adr_deprecate) with entity ID in value"
  - "Deprecated decisions show no action buttons (static, read-only)"
  - "Approved and Committed decisions both show Deprecate button (danger style)"

patterns-established:
  - "_update_adr_pinned_message: centralized helper for rebuilding pinned ADR blocks after any transition"

issues-created: []

# Metrics
duration: 3min
completed: 2026-02-04
---

# Phase 10 Plan 05: ADR Lifecycle UI Summary

**Status badges and lifecycle action buttons on pinned ADR messages with auto-sync on every transition**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-04T15:39:50Z
- **Completed:** 2026-02-04T15:43:10Z
- **Tasks:** 4
- **Files modified:** 2

## Accomplishments
- Pinned ADR messages now display status badge showing current lifecycle state
- Pinned ADR messages include appropriate lifecycle action buttons (Propose, Approve/Object, Deprecate)
- All existing lifecycle handlers now auto-update pinned ADR messages via `_update_adr_pinned_message`
- ISS-001 (pinned ADR no lifecycle UI) closed

## Task Commits

Each task was committed atomically:

1. **Task 1: Add status badge and action buttons to build_adr_post_blocks** - `5f98f61` (feat)
2. **Task 2: Register ADR pinned message action handlers** - `8b70e1f` (feat)
3. **Task 3: Update pinned ADR message on lifecycle transitions** - `6e43560` (feat)
4. **Task 4: Run tests** - no commit (verification only, 20 passed / 9 skipped)

## Files Created/Modified
- `src/slack/blocks/decisions.py` - Added STATUS_BADGES, _build_lifecycle_buttons, extended build_adr_post_blocks with status/entity_id params
- `src/slack/handlers/actions.py` - Added ADR_LIFECYCLE_PATTERN handler, _update_adr_pinned_message helper, wired into all transition handlers

## Decisions Made
- Lifecycle buttons use fixed action_ids (adr_propose, adr_approve, adr_object, adr_deprecate) consistent with ISS-004 pattern from Plan 10-01
- Deprecated decisions are static (no buttons) to prevent accidental actions
- Both Approved and Committed states show Deprecate button since deprecation is available for committed decisions
- Amend flow preserves old ADR amended notice while updating new ADR with lifecycle buttons

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Phase 10 complete - all 5 plans finished
- All 8 code review issues addressed (7 fixed, 1 deferred: ISS-002)
- v2.1 milestone complete

---
*Phase: 10-code-review-polish*
*Completed: 2026-02-04*
