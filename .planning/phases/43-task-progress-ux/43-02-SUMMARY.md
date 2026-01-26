---
phase: 43-task-progress-ux
plan: 02
subsystem: slack
tags: [task-plan, status-card, ux, active-step]

# Dependency graph
requires:
  - phase: 35
    provides: TaskPlan and Task schemas, TaskStatusUpdater
provides:
  - active_step field on Task for real-time action feedback
  - set_active_step/clear_active_step methods for step management
  - Status card display of active step for RUNNING tasks
  - update_step convenience method in TaskStatusUpdater
affects: [43-03, 43-04, task-executor, status-card]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Active step display with em dash separator in status card
    - Step reporting at intent dispatch points

key-files:
  created: []
  modified:
    - src/schemas/task_plan.py
    - src/slack/blocks/task_plan.py
    - src/slack/task_status_updater.py
    - src/graph/nodes/task_executor.py

key-decisions:
  - "Active step shown with em dash separator: 'title — step'"
  - "Step text should be concise (<40 chars)"
  - "Step changes respect existing throttling (not significant events)"
  - "Clear active step on task completion or failure"

patterns-established:
  - "set_active_step/clear_active_step for task step management"
  - "Intent-specific step descriptions in task executor"

issues-created: []

# Metrics
duration: 8min
completed: 2026-01-26
---

# Phase 43 Plan 02: Specific Action Feedback Summary

**active_step field on Task with status card display showing what MARO is currently doing during long operations**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-26T16:30:00Z
- **Completed:** 2026-01-26T16:38:00Z
- **Tasks:** 5
- **Files modified:** 4

## Accomplishments

- Added `active_step` optional field to Task schema for tracking current action
- Status card now displays active step for RUNNING tasks with format: "title — step"
- Added `set_active_step()` and `clear_active_step()` helper methods to Task
- Task executor reports intent-specific steps before dispatching to handlers
- TaskStatusUpdater has new `update_step()` convenience method for granular updates

## Task Commits

Each task was committed atomically:

1. **Task 1: Add active_step field to Task schema** - `adc7ecf` (feat)
2. **Task 2: Update status card to show active step** - `3be31c0` (feat)
3. **Task 3: Add set_active_step method to Task** - `48ab6bc` (feat)
4. **Task 4: Update task executors to report steps** - `a4560c4` (feat)
5. **Task 5: Wire step updates through TaskStatusUpdater** - `4ac785e` (feat)

## Files Created/Modified

- `src/schemas/task_plan.py` - Added active_step field and set_active_step/clear_active_step methods
- `src/slack/blocks/task_plan.py` - Display active step with em dash separator for RUNNING tasks
- `src/slack/task_status_updater.py` - Added update_step convenience method
- `src/graph/nodes/task_executor.py` - Added step reporting at key dispatch points

## Decisions Made

- Active step displayed with em dash separator: "Generate stories — Parsing requirements"
- Step text should be concise (<40 chars) for clean UI display
- Step changes use regular throttling (not bypassing like significant events)
- Intent-specific step descriptions: "Searching Jira", "Analyzing request", etc.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Active step infrastructure complete
- Ready for 43-03 (Elapsed Time Indicator) which can combine with active step display
- Status card now shows real-time feedback of what MARO is doing

---
*Phase: 43-task-progress-ux*
*Completed: 2026-01-26*
