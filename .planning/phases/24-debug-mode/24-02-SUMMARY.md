---
phase: 24-debug-mode
plan: 02
subsystem: debug
tags: [slack-blocks, slash-commands, debug-mode]

# Dependency graph
requires:
  - phase: 24-01
    provides: DebugStore and DebugCollector foundation
provides:
  - /maro debug slash command with on/off/status/state subcommands
  - Updated help documentation with all slash commands
  - Debug block builders for Slack output formatting
affects: [24-03-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [debug-block-builders]

key-files:
  created:
    - src/slack/blocks/debug.py
  modified:
    - src/slack/handlers/commands.py
    - src/slack/onboarding.py
    - src/slack/blocks/__init__.py

key-decisions:
  - "Reuse _build_debug_status_blocks and _build_debug_state_blocks inline in commands.py for direct database access"
  - "Create separate src/slack/blocks/debug.py with pure formatting functions for reuse"
  - "Group help commands into logical categories: Getting Started, Issue Tracking, Sync, Configuration, Debugging"

patterns-established:
  - "Debug blocks module provides pure formatting functions that accept data, not database connections"
  - "Commands.py handles database access and passes data to block builders"

issues-created: []

# Metrics
duration: 6min
completed: 2026-01-22
---

# Phase 24 Plan 02: Debug Slash Command Summary

**/maro debug slash command with on/off/status/state subcommands and comprehensive help documentation**

## Performance

- **Duration:** 6 min
- **Started:** 2026-01-22T14:04:57Z
- **Completed:** 2026-01-22T14:10:54Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Implemented `/maro debug` slash command with routing for on/off/status/state actions
- Created `_handle_maro_debug` async handler for debug mode control
- Built `_build_debug_status_blocks` for quick health check display (debug mode, channel mode, listening, workitems, Jira registry)
- Built `_build_debug_state_blocks` for full internal state dump (channel context, workitem registry, Jira registry)
- Updated help blocks with comprehensive slash command documentation grouped by category
- Created `src/slack/blocks/debug.py` with reusable formatting functions
- Added `build_debug_output_blocks` for DebugCollector to Slack blocks conversion

## Task Commits

Each task was committed atomically:

1. **Task 1: Add debug subcommand to _handle_maro_command_async** - `5cc962c` (feat)
2. **Task 2: Update help and onboarding to include all slash commands** - `8907763` (feat)
3. **Task 3: Create debug state formatting helpers** - `7932804` (feat)

## Files Created/Modified

- `src/slack/handlers/commands.py` - Added debug subcommand routing and handlers
- `src/slack/onboarding.py` - Updated get_help_blocks with all slash commands
- `src/slack/blocks/debug.py` - New module with debug block builders
- `src/slack/blocks/__init__.py` - Added debug block exports

## Decisions Made

- Implemented database access inline in commands.py handlers rather than passing connections to block builders, maintaining separation of concerns (block builders are pure formatting functions)
- Grouped help commands into logical categories (Getting Started, Issue Tracking, Sync, Configuration, Debugging) for better scanability

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Debug slash command fully functional with all subcommands
- Ready for Plan 03 (Integration) to wire DebugCollector into message flow
- Debug output can now be triggered manually via `/maro debug state`

---
*Phase: 24-debug-mode*
*Completed: 2026-01-22*
