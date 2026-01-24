# Plan 35-08 Summary: Dispatch Integration for TaskPlan Flow

**Status:** Completed
**Commit:** b36adf5

## Objective

Integrate TaskPlan flow into dispatch and complete end-to-end wiring. Connect all pieces: when multi-intent detected, post status card, run tasks, update UI. This completes the Phase 35 implementation.

## Implementation

### Files Modified

1. **`src/slack/handlers/dispatch.py`**
   - Added Phase 35 TaskPlan imports
   - Added 5 new action handlers for TaskPlan lifecycle events
   - Implemented complete dispatch handling for multi-intent flow

2. **`src/graph/intent.py`**
   - Updated `intent_router_node` to use `return_proposal=True`
   - Store `TaskPlanProposal` in `intent_result` for task_decomposer
   - Handle both `IntentResult` and `TaskPlanProposal` return types
   - Log multi-intent detection

3. **`src/graph/nodes/task_decomposer.py`**
   - Updated return value to include `decision_result` with `action: "task_plan_created"`
   - Triggers dispatch handler to post announcement and status card

## Key Components

### Dispatch Action Handlers

```python
# Phase 35: TaskPlan action handlers
elif action == "task_plan_created":
    await _handle_task_plan_created(client, result, identity)

elif action == "task_confirmation_required":
    await _handle_task_confirmation(client, result, identity)

elif action == "task_plan_complete":
    await _handle_task_plan_complete(client, result, identity)

elif action == "task_plan_blocked":
    await _handle_task_plan_blocked(client, result, identity)

elif action == "task_failed":
    await _handle_task_failed(client, result, identity)
```

### Handler Functions

1. **`_handle_task_plan_created`**
   - Posts canonical announcement: "Got it. I see N actions..."
   - Posts status card via TaskStatusUpdater
   - Logs plan creation with task counts

2. **`_handle_task_confirmation`**
   - Updates status card to show blocked task
   - Posts reminder message with approval instructions

3. **`_handle_task_plan_complete`**
   - Flushes pending status updates
   - Posts final status card update
   - Posts completion summary to channel (not just thread)

4. **`_handle_task_plan_blocked`**
   - Updates status card
   - Lists blocked tasks waiting for input

5. **`_handle_task_failed`**
   - Updates status card
   - Posts error message with retry option

### Intent Router Updates

```python
# Phase 35: Use return_proposal=True to get TaskPlanProposal for multi-intent
classification_result = await classify_intent(
    latest_human_message,
    conversation_context,
    active_draft,
    return_proposal=True,
)

# Handle both return types
if isinstance(classification_result, TaskPlanProposal):
    proposal = classification_result
    result = proposal.to_single_intent()
else:
    result = classification_result
    proposal = None

# Store TaskPlanProposal in intent_result for task_decomposer
if proposal:
    intent_result_dict["task_plan_proposal"] = proposal.model_dump()
    intent_result_dict["super_mode"] = proposal.primary_mode.value
```

### Task Decomposer Updates

```python
# Return with action for dispatch to post status card
return {
    "task_plan": task_plan.model_dump(),
    "decision_result": {
        "action": "task_plan_created",
        "plan_id": plan_id,
        "task_count": len(tasks),
        "auto_count": auto_executable_count,
    },
}
```

## End-to-End Flow

1. **User sends compound request** (e.g., "create stories and check duplicates")
2. **Intent Router** classifies with `return_proposal=True`, detects multi-intent
3. **Graph routes** to `task_decomposer` via `route_after_intent`
4. **Task Decomposer** creates TaskPlan, returns `action: "task_plan_created"`
5. **Dispatch** receives action, calls `_handle_task_plan_created`
6. **Handler posts**:
   - Announcement: "Got it. I see 2 actions..."
   - Status card: Task list with buttons
7. **Task Executor** runs safe tasks automatically
8. **Status card updates** as tasks progress
9. **Completion summary** posted to channel when all done

## Verification

All verification commands pass:
```bash
python -c "from src.slack.handlers.dispatch import _dispatch_result; print('OK')"
# dispatch.py OK

python -c "from src.graph.intent import intent_router_node; print('OK')"
# intent.py OK

python -c "from src.graph.nodes.task_decomposer import task_decomposer_node; print('OK')"
# task_decomposer.py OK
```

## Dependencies

- **35-05**: Task executor node for executing tasks
- **35-06**: TaskStatusUpdater and block builders
- **35-07**: Button handlers for user interactions

## Integration Points

1. **Dispatch Layer**: Routes TaskPlan actions to appropriate handlers
2. **Intent Classification**: Detects multi-intent and creates proposal
3. **Graph Routing**: Routes multi-intent to task_decomposer
4. **Task Decomposer**: Triggers dispatch via decision_result
5. **Slack Messaging**: Posts announcement and status card

## User Experience

When user sends a multi-intent message:
```
User: Check Jira for duplicates and create stories for the auth epic

Bot: Got it. I see 2 actions:
1. Search Jira for duplicates
2. Create stories for SCRUM-123

Executing 1 now. For 2 - OK?

[Status Card]
MARO Plan - BUILD (0/2 tasks)
1) :hourglass: THINK: Search Jira for duplicates
2) :hourglass: BUILD: Create stories (waiting for approval)
[Cancel plan] [(2) Approve] [(2) Reject]
```

## Notes

- Context-aware classification (thread_context) doesn't yet support return_proposal
- Backward compatibility maintained via `to_single_intent()` conversion
- All handlers use async Slack client for proper error handling
