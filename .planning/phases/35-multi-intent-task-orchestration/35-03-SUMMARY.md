---
phase: 35-multi-intent-task-orchestration
plan: 03
status: complete
---

# Plan 35-03 Summary: Task Safety Classification

## Changes Made

### Task 1: Created safety classification module (`src/graph/safety.py`)

- Created `MODE_SAFETY_MAP`: Maps SuperMode to default SafetyLevel
  - THINK/CHAT -> AUTO_EXECUTE
  - BUILD/OPERATE/DECIDE -> REQUIRES_CONFIRMATION

- Created `INTENT_SAFETY_OVERRIDES` for specific intents that deviate from mode default:
  - DRAFT_REFINE -> AUTO_EXECUTE (just drafts, no Jira)
  - DRAFT_TRANSFORM -> AUTO_EXECUTE (just drafts, no Jira)
  - JIRA_SEARCH -> AUTO_EXECUTE (read-only)

- Implemented `classify_task_safety(task)` with priority rules:
  1. JIRA side effect -> always REQUIRES_CONFIRMATION
  2. Intent override -> use override
  3. Fall back to mode-based default

- Added helper functions:
  - `is_task_auto_executable(task)` - check if task can auto-execute
  - `get_tasks_needing_confirmation(tasks)` - filter dangerous tasks
  - `get_auto_executable_tasks(tasks)` - filter safe tasks

### Task 2: Integrated safety into Task creation (`src/schemas/task_plan.py`)

- Made `safety_level` field optional with auto-computation via `model_validator`
- Added `@model_validator(mode='after')` that calls `classify_task_safety()` when safety_level is None
- Added Task methods:
  - `can_auto_execute()` - returns True if AUTO_EXECUTE
  - `needs_confirmation()` - returns True if REQUIRES_CONFIRMATION
- Added TaskPlan methods:
  - `get_safe_tasks()` - get all auto-executable tasks
  - `get_confirmation_tasks()` - get all tasks needing confirmation
  - `has_dangerous_tasks()` - check if any tasks need confirmation

### Task 3: Added side effect detection (`src/graph/safety.py`)

- Created `INTENT_SIDE_EFFECTS` mapping:
  - JIRA-affecting: WORKITEM_CREATE, JIRA_COMMAND, CHANGE_REQUEST, SYNC_REQUEST, TICKET_ACTION
  - SLACK-affecting: REVIEW, DISCUSSION
  - Registry+Slack: DECISION
  - Registry-only: DRAFT_REFINE, DRAFT_TRANSFORM
  - No side effects: JIRA_SEARCH, META, OPS, AMBIGUOUS

- Implemented `infer_side_effects(intent)` function
- Created `create_task_with_inferred_safety()` factory function that:
  - Infers side effects from intent
  - Creates Task with auto-computed safety level

## Commits Created

1. `3ed9349` - feat(phase35): add task safety classification system
2. `798a894` - feat(phase35): add side effect inference for tasks

## Verification Results

```
[x] THINK/CHAT -> AUTO_EXECUTE: THINK=True, CHAT=True
[x] BUILD/OPERATE/DECIDE -> REQUIRES_CONFIRMATION: BUILD=True, OPERATE=True, DECIDE=True
[x] JIRA side effect -> REQUIRES_CONFIRMATION: True
[x] DRAFT_REFINE/DRAFT_TRANSFORM -> AUTO_EXECUTE: REFINE=True, TRANSFORM=True
[x] Task.can_auto_execute() works: True
[x] Task.needs_confirmation() works: True
[x] TaskPlan.get_safe_tasks() works: 4 safe tasks
[x] TaskPlan.get_confirmation_tasks() works: 3 confirmation tasks
[x] TaskPlan.has_dangerous_tasks() works: True
```

All verification commands from the plan passed successfully.

## Ready Status

**Ready for Plan 35-05: Status Card Rendering**

The safety classification system is complete and integrated. Plan 35-05 can use:
- `Task.can_auto_execute()` to determine which tasks show auto-execute indicators
- `Task.needs_confirmation()` to determine which tasks show confirmation buttons
- `TaskPlan.has_dangerous_tasks()` to decide overall status card layout
- `create_task_with_inferred_safety()` for creating properly classified tasks
