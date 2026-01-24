---
phase: 29-sync-on-demand
plan: 04
subsystem: sync
tags: [jira, sync, preflight, handlers, slack-buttons]

# Dependency graph
requires:
  - phase: 29-02
    provides: PreflightService with conflict classification
  - phase: 29-01
    provides: JiraRegistryStore sync tracking fields
provides:
  - Preflight check in draft commit flow (duplicate detection)
  - Preflight check in ticket update actions (conflict detection)
  - Button handlers for all preflight conflict resolution options
affects: [draft-approval, ticket-updates, jira-operations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Preflight before Jira ops pattern
    - Button payload with pending_action for stateful resolution
    - JSON payloads extended with channel_id/thread_ts for handlers

key-files:
  created:
    - src/slack/handlers/preflight.py
  modified:
    - src/slack/handlers/draft.py
    - src/slack/handlers/dispatch.py
    - src/slack/handlers/__init__.py
    - src/slack/router.py

key-decisions:
  - "Preflight for creates: duplicate detection via summary matching"
  - "Preflight for updates: use PreflightService check_update()"
  - "IDEMPOTENT auto-succeeds without UI (just message)"
  - "Button payloads include pending_action for stateful handling"
  - "preflight_use_jira same as pull_only; preflight_use_channel same as proceed"

patterns-established:
  - "Preflight integration pattern: check -> classify -> show UI or proceed"

issues-created: []

# Metrics
duration: 8min
completed: 2026-01-23
---

# Phase 29 Plan 04: Integrate Preflight Sync into Jira Handlers Summary

**Preflight conflict detection integrated into draft commit and ticket update flows with full button handler support**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-24T00:15:00Z
- **Completed:** 2026-01-24T00:23:00Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Added `_check_preflight_for_create()` to detect duplicate tickets before creation
- Built `_build_create_preflight_blocks()` for create conflict UI (idempotent/potential duplicate)
- Integrated preflight check into ticket update flow with PreflightService
- Created full preflight button handler module with 6 handlers
- Registered handlers in router.py via `register_preflight_handlers()`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add preflight check to draft commit flow** - `1aad991` (feat)
2. **Task 2: Add preflight check to ticket actions** - `1038599` (feat)
3. **Task 3: Add preflight button handlers** - `6232ca8` (feat)

## Files Created/Modified

- `src/slack/handlers/preflight.py` - NEW: All preflight button handlers
- `src/slack/handlers/draft.py` - `_check_preflight_for_create()` and `_build_create_preflight_blocks()`
- `src/slack/handlers/dispatch.py` - `_check_preflight_for_action()` and update flow integration
- `src/slack/handlers/__init__.py` - Export preflight handlers
- `src/slack/router.py` - Register preflight handlers

## Decisions Made

1. **Create preflight as duplicate detection** - For creates, preflight checks if summary matches existing tracked ticket (idempotent or potential duplicate)
2. **Update preflight uses PreflightService** - Full 4-type conflict classification from Phase 29-02
3. **Button handler simplification** - `use_jira` behaves same as `pull_only`; `use_channel` same as `proceed`
4. **Pending action in button payloads** - Button values include the full pending_action dict for stateful handlers

## Deviations from Plan

- Transition support deferred - current codebase doesn't have a direct transition action_type, updates go through preview flow
- Some buttons (show_diff, remove_tracking, reopen) marked for future implementation

## Issues Encountered

None

## Verification

- [x] Draft commit flow runs preflight before Jira create
- [x] Ticket actions (update) run preflight before execution
- [x] IDEMPOTENT conflicts auto-succeed without UI (just message)
- [x] SAFE_DRIFT shows warning with proceed default
- [x] REAL_CONFLICT blocks and shows choice buttons
- [x] STRUCTURAL blocks and explains why
- [x] All preflight buttons work: proceed, pull_only, use_jira, use_channel, cancel
- [x] Pending action state preserved for button handlers

## Next Phase Readiness

- Phase 29 complete - all 4 plans executed
- Preflight sync fully integrated into Jira operations
- Ready to finalize Phase 29 or proceed to Phase 30

---
*Phase: 29-sync-on-demand*
*Completed: 2026-01-23*
