---
phase: 35-multi-intent-task-orchestration
plan: 06
status: completed
completed_at: 2025-01-24
---

# Plan 35-06: Status Card UI and TaskStatusUpdater

## Objective

Create Status Card UI and throttled updater for TaskPlan progress. Visual feedback showing TaskPlan execution status with single editable message that updates in place with throttling to avoid Slack rate limits.

## Completed Tasks

### Task 1: Status Card Blocks
**File:** `src/slack/blocks/task_plan.py`

Created Slack Block Kit components for TaskPlan status card:

- **TASK_STATUS_EMOJI mapping**: Maps TaskStatus enum to Slack emoji codes
  - PENDING -> `:hourglass_flowing_sand:`
  - RUNNING -> `:arrows_counterclockwise:`
  - BLOCKED -> `:double_vertical_bar:`
  - DONE -> `:white_check_mark:`
  - CANCELED -> `:x:`

- **PLAN_STATUS_EMOJI mapping**: Maps TaskPlanStatus enum to Slack emoji codes

- **build_task_plan_blocks(task_plan)**: Returns Slack Block Kit blocks with:
  - Header section with plan emoji, mode label, task count (done/total)
  - Divider
  - Task list with numbered entries showing emoji, mode, title, progress, status suffix
  - Actions block with Cancel button and task-specific Approve/Reject buttons
  - Context footer with version for debugging
  - Handles Slack's 5-button-per-actions-block limit

- **build_plan_complete_message(task_plan)**: Short completion summary for channel announcement

- **build_plan_canceled_message(task_plan, user_id)**: Cancellation message with user mention

### Task 2: TaskStatusUpdater with Throttling
**File:** `src/slack/task_status_updater.py`

Created updater class with rate limiting:

- **MIN_UPDATE_INTERVAL = 1.5 seconds**: Conservative throttle for Slack rate limits
- **SIGNIFICANT_EVENTS set**: Events that bypass throttling:
  - task_started, task_completed, task_blocked, task_failed
  - plan_completed, plan_canceled

- **TaskStatusUpdater class**:
  - `__init__(client)`: Initializes with AsyncWebClient, tracking dicts for last_update and pending_updates
  - `post_initial_card(task_plan, channel_id, thread_ts)`: Posts initial card, stores message_ts in DB
  - `update_card(task_plan, channel_id, event)`: Throttled updates with significant event bypass
  - `_do_update(task_plan, channel_id)`: Performs actual chat.update call
  - `flush_pending(plan_id, channel_id)`: Ensures final state shown on plan completion
  - `delete_card(task_plan, channel_id)`: Optional cleanup

### Task 3: Canonical UX Response Builder
**File:** `src/slack/blocks/task_plan.py` (same file as Task 1)

- **build_multi_intent_announcement(task_plan)**: Builds the canonical response:
  ```
  Got it. I see 3 actions:
  1. Create list of Epics from Decisions
  2. Check duplicates in Jira
  3. Provide architecture recommendations

  Executing 1 and 2 now. For 3 - OK?
  ```

- **build_task_summary_line(task, include_status)**: Single-line summary helper

## Verification Results

```bash
python -c "from src.slack.blocks.task_plan import build_task_plan_blocks; print('OK')"
# OK

python -c "from src.slack.task_status_updater import TaskStatusUpdater; print('OK')"
# OK

python -c "from src.slack.blocks.task_plan import build_multi_intent_announcement; print('OK')"
# OK
```

## UI Vision Implemented

```
:hammer_and_wrench: *MARO Plan* - BUILD (1/3 tasks)

1) :white_check_mark: *OPERATE*: Jira duplicate check
2) :arrows_counterclockwise: *BUILD*: Generate stories (3/12)
3) :double_vertical_bar: *DECIDE*: Create in Jira _(waiting for approval)_

[Cancel plan]  [(3) Approve]  [(3) Reject]

Plan v1
```

## Files Created/Modified

| File | Change |
|------|--------|
| `src/slack/blocks/task_plan.py` | Created - Status card blocks and announcement builder |
| `src/slack/task_status_updater.py` | Created - Throttled updater class |

## Integration Points

- Uses `src/schemas/task_plan.py` for TaskPlan, Task, TaskStatus, TaskPlanStatus
- Uses `src/db/task_plan_store.py` for persisting ui_message_ts
- Uses `src/db/connection.py` for async DB connection
- Ready for use by TaskPlanExecutor (35-08)

## Commit

Committed in: `38ae3c5 feat(phase35): add task executor node for multi-intent orchestration`

## Next Steps

- Plan 35-07: Button handlers for Approve/Reject/Cancel
- Plan 35-08: TaskPlanExecutor integration with status updates
