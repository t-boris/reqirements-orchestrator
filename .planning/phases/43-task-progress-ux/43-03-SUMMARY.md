---
phase: 43-task-progress-ux
plan: 03
subsystem: ui
tags: [slack, elapsed-time, timer, asyncio, progress]

# Dependency graph
requires:
  - phase: 43-02
    provides: active_step field in Task schema
provides:
  - format_elapsed_time utility
  - elapsed time display in status card
  - periodic timer for live updates
affects: [43-04, task-progress-ux]

# Tech tracking
tech-stack:
  added: []
  patterns: [module-level timer registry, background asyncio task]

key-files:
  created: []
  modified:
    - src/slack/blocks/task_plan.py
    - src/slack/task_status_updater.py
    - src/slack/handlers/dispatch/task_plan.py

key-decisions:
  - "Module-level timer registry for cross-instance management"
  - "Timer auto-stops when task completes or plan finishes"
  - "Only show elapsed time if >5 seconds to avoid clutter"

patterns-established:
  - "Module-level asyncio.Task registry pattern for timer management"

issues-created: []

# Metrics
duration: 12min
completed: 2026-01-26
---

# Phase 43 Plan 03: Elapsed Time Indicator Summary

**Live elapsed time display for running tasks with auto-updating timer**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-26T06:18:00Z
- **Completed:** 2026-01-26T06:30:00Z
- **Tasks:** 4
- **Files modified:** 3

## Accomplishments

- Added format_elapsed_time() utility for human-readable duration formatting
- Integrated elapsed time display into TaskPlan status card for running tasks
- Implemented background timer that updates status card every 5 seconds
- Connected timer lifecycle to task lifecycle (start/stop at appropriate events)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add elapsed time formatter utility** - `6f31eff` (feat)
2. **Task 2: Display elapsed time in status card** - `1511055` (feat)
3. **Task 3: Add periodic refresh for long-running tasks** - `10de43a` (feat)
4. **Task 4: Integrate timer with task lifecycle** - `263b704` (feat)

## Files Created/Modified

- `src/slack/blocks/task_plan.py` - Added format_elapsed_time() and elapsed display in build_task_plan_blocks()
- `src/slack/task_status_updater.py` - Added start_elapsed_timer() and stop_elapsed_timer() with module-level registry
- `src/slack/handlers/dispatch/task_plan.py` - Integrated timer start/stop in task_plan_created, task_plan_complete, task_plan_blocked, task_failed, task_rejected handlers

## Decisions Made

- **Module-level timer registry:** Used `_active_timers` dict at module level instead of instance attribute to allow different TaskStatusUpdater instances to manage the same timers
- **Timer auto-stop:** Timer automatically stops when task completes, plan finishes, or plan is canceled - no resource leaks
- **5-second threshold:** Only display elapsed time if >5 seconds have passed to avoid cluttering UI with fast operations
- **Elapsed time format:** "<5s" for very short, "Xs" for seconds, "Xm Ys" for longer durations

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Elapsed time indicator complete, ready for 43-04 (Visual State Transition Feedback)
- Timer infrastructure can be reused for other periodic updates
- All acceptance criteria met:
  - Running tasks show elapsed time after 5s
  - Time updates every ~5 seconds
  - Timer stops immediately when task completes
  - No resource leaks from orphaned timers
  - Elapsed time format is readable (1m 30s, not 90s)

---
*Phase: 43-task-progress-ux*
*Completed: 2026-01-26*
