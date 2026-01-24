# Plan 35-07 Summary: Button Handlers for TaskPlan Controls

**Status:** Completed
**Commit:** 190939e

## Objective

Create button handlers for TaskPlan controls with version binding. Handle user interactions with status card buttons (Approve, Reject, Cancel). Version binding prevents stale actions from succeeding.

## Implementation

### Files Created

1. **`src/slack/handlers/task_plan.py`** (new file)
   - Complete button handler module for TaskPlan interactions
   - Follows existing handler patterns from `duplicates.py`, `draft.py`

### Files Modified

2. **`src/slack/router.py`**
   - Added import for `register_task_plan_handlers`
   - Called registration function in handler setup section

## Key Components

### Idempotency Helpers

```python
def parse_task_button_value(value: str) -> tuple[str, str, int] | None:
    """Parse task button value: {plan_id}:{task_id}:{version}"""

def parse_plan_button_value(value: str) -> tuple[str, int] | None:
    """Parse plan button value: {plan_id}:{version}"""

async def validate_task_action(
    plan_id: str,
    task_id: str,
    version: int,
    expected_status: TaskStatus = TaskStatus.BLOCKED,
) -> tuple[TaskPlan | None, Task | None, str | None]:
    """Validate task action with version and status checks."""

async def validate_plan_action(
    plan_id: str,
    version: int,
) -> tuple[TaskPlan | None, str | None]:
    """Validate plan-level action with version check."""
```

### Button Handlers

1. **`handle_task_approve`**
   - Parses button value `{plan_id}:{task_id}:{version}`
   - Validates version (rejects stale actions)
   - Calls `handle_task_approval` from task_executor with `approved=True`
   - Updates status card via TaskStatusUpdater

2. **`handle_task_reject`**
   - Same parsing and validation
   - Calls `handle_task_approval` with `approved=False`
   - Posts ephemeral message about cancellation
   - Cascade cancels dependent tasks

3. **`handle_plan_cancel`**
   - Parses button value `{plan_id}:{version}`
   - Validates version
   - Cancels entire plan via `TaskPlanStore.cancel_plan()`
   - Updates status card, posts cancellation message

### Registration

```python
def register_task_plan_handlers(app) -> None:
    """Register TaskPlan button handlers with Slack app."""
    @app.action("task_approve")
    def on_task_approve(ack, body, client, respond):
        ack()
        _run_async(handle_task_approve(client, body, respond))

    @app.action("task_reject")
    def on_task_reject(ack, body, client, respond):
        ack()
        _run_async(handle_task_reject(client, body, respond))

    @app.action("task_plan_cancel")
    def on_plan_cancel(ack, body, client, respond):
        ack()
        _run_async(handle_plan_cancel(client, body, respond))
```

## Version Binding Pattern

Button values include the plan version at creation time:
```python
# In build_task_plan_blocks (35-06):
value = f"{task_plan.plan_id}:{task.task_id}:{task_plan.version}"

# In handler, reject if version changed:
if task_plan.version != version:
    await respond(
        text="Action failed: This action is outdated. The plan has been updated.",
        response_type="ephemeral",
    )
```

## Verification

All verification commands pass:
```bash
python -c "from src.slack.handlers.task_plan import register_task_plan_handlers; print('OK')"
# OK

grep -q "register_task_plan_handlers" src/slack/router.py && echo "OK"
# OK

python -c "from src.slack.handlers.task_plan import validate_task_action; print('OK')"
# OK
```

## Dependencies

- **35-05**: `handle_task_approval` function from task_executor
- **35-06**: `build_plan_canceled_message` from task_plan blocks, `TaskStatusUpdater`

## Integration Points

1. **Slack Actions**: Registered for `task_approve`, `task_reject`, `task_plan_cancel`
2. **TaskPlanStore**: Uses `get()`, `cancel_plan()` for persistence
3. **TaskStatusUpdater**: Updates status card after each action
4. **task_executor**: Delegates approval logic to `handle_task_approval()`

## User Experience

1. **Approve**: Task continues execution, card updates
2. **Reject**: Task and dependents canceled, ephemeral feedback
3. **Cancel Plan**: All tasks canceled, message posted to thread
4. **Stale Action**: Ephemeral message, card refreshed to current state
