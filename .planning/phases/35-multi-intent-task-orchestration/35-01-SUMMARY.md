---
phase: 35-multi-intent-task-orchestration
plan: 01
subsystem: orchestration
tags: [taskplan, pydantic, psycopg, jsonb, multi-intent]

requires:
  - phase: 31-architecture-hardening
    provides: SuperMode enum for user-facing modes
  - phase: 33-anchor-message-architecture
    provides: Anchor context pattern for task targeting

provides:
  - TaskPlan and Task Pydantic models for multi-intent orchestration
  - TaskPlanStore for database persistence
  - TaskStatus, TaskPlanStatus, SafetyLevel, SideEffect enums
  - Helper methods for task execution orchestration

affects: [35-02, 35-03, 35-04, 35-05, 35-06]

tech-stack:
  added: []
  patterns:
    - TaskPlan as JSONB tasks storage (atomic updates)
    - Optimistic locking with version check
    - Safety level mapping from SuperMode

key-files:
  created:
    - src/schemas/task_plan.py
    - src/db/task_plan_store.py
  modified:
    - src/__main__.py

key-decisions:
  - "Tasks stored as JSONB array in task_plans table (not separate table)"
  - "Optimistic locking via version check on update"
  - "SafetyLevel maps from SuperMode: THINK/CHAT -> AUTO_EXECUTE, BUILD/OPERATE/DECIDE -> REQUIRES_CONFIRMATION"
  - "TaskPlan.compute_status() derives plan status from aggregate task statuses"

patterns-established:
  - "Task dependency checking via depends_on list"
  - "Version bumping for button idempotency"

issues-created: []

duration: 12min
completed: 2026-01-24
---

# Phase 35 Plan 01: TaskPlan and Task Schemas Summary

**Foundation data model for multi-intent orchestration with TaskPlan/Task Pydantic models, TaskPlanStore persistence, and safety classification**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-24T10:00:00Z
- **Completed:** 2026-01-24T10:12:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- TaskPlan and Task Pydantic models with all required enums
- TaskPlanStore with CRUD operations following WorkItemStore pattern
- Database table creation integrated into application startup
- Helper methods for task execution orchestration (get_next_pending_task, all_done, etc.)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create TaskPlan/Task schemas** - `4fbfc5c` (feat)
2. **Task 2: Create TaskPlanStore** - `dd8b116` (feat)
3. **Task 3: Database migration** - `2926de1` (feat)

## Files Created/Modified

- `src/schemas/task_plan.py` - TaskPlan, Task, TaskStatus, TaskPlanStatus, SafetyLevel, SideEffect enums and models
- `src/db/task_plan_store.py` - TaskPlanStore with CRUD operations and optimistic locking
- `src/__main__.py` - Added TaskPlanStore.create_tables() to startup

## Decisions Made

- **JSONB for tasks:** Store tasks as JSONB array in task_plans table rather than separate table for atomic updates
- **Optimistic locking:** Version check on update prevents concurrent modification issues
- **Safety from SuperMode:** SafetyLevel derives from SuperMode (THINK/CHAT = AUTO_EXECUTE, others = REQUIRES_CONFIRMATION)
- **Computed status:** TaskPlan.compute_status() derives plan status from task statuses

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- TaskPlan and Task schemas ready for use in intent classification
- TaskPlanStore ready for persistence
- Next: Plan 02 - Intent → TaskPlan conversion with multi-intent detection

---
*Phase: 35-multi-intent-task-orchestration*
*Completed: 2026-01-24*
