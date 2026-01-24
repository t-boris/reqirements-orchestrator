---
phase: 36-question-engine-conversation-driver
plan: 05
status: completed
completed_at: 2026-01-24
---

# Plan 36-05: Question Executor Integration - Summary

## Objective
Integrate question execution into TaskPlan executor so that question tasks properly block execution, enforce budget limits, and resume after answers.

## Files Modified
- `src/graph/nodes/question_executor.py` (created)
- `src/graph/nodes/task_executor.py` (modified)

## Changes Made

### Task 1: Created question_executor_node
Created new file `src/graph/nodes/question_executor.py` with:

1. **`question_executor_node(state, task, task_plan)`**
   - Checks question budget via `BudgetTracker.is_exhausted()`
   - Returns `budget_exhausted` action when limit reached (includes pending_fields for partial preview)
   - Records question asked via `budget.record_question_asked()`
   - Transitions conversation to ACTIVE mode via `ConversationModeStore.transition()`
   - Sets task status to BLOCKED with `requires_user_input=True`
   - Returns `question_posted` action with full question data for Slack UI

2. **`_get_pending_fields(task_plan)`**
   - Helper to extract target fields from pending question tasks
   - Used for budget_exhausted response to show what fields remain

### Task 2: Integrated question execution into task_executor_node
Modified `src/graph/nodes/task_executor.py`:

1. **Updated `_dispatch_task` signature**
   - Added `task_plan` parameter: `_dispatch_task(state, task, task_plan)`
   - Checks `task.is_question` first, routes to `question_executor_node`
   - Falls through to existing intent-based routing otherwise

2. **Updated `_execute_task` to handle question results**
   - Checks for `question_posted` action - sets plan BLOCKED, returns without continuing
   - Checks for `budget_exhausted` action - sets plan BLOCKED, returns for partial preview
   - Only marks task DONE and continues for non-question results

### Task 3: Added handle_question_answer
Added to `src/graph/nodes/question_executor.py`:

1. **`handle_question_answer(state, plan_id, task_id, patch)`**
   - Loads TaskPlan from store
   - Finds the question task by ID
   - Applies answer: sets `answer`, `status=ANSWERED`, `answered_at`
   - Checks confidence against `CONFIDENCE_THRESHOLD` (0.7)
   - Low confidence: returns `low_confidence_answer` action for clarification
   - High confidence: marks task DONE, plan PENDING, increments version
   - Resets budget counter via `budget.record_answer_received()`
   - Continues execution by calling `task_executor_node` with updated state

## Verification
All verification commands passed:
```bash
python -c "from src.graph.nodes.question_executor import question_executor_node; print('OK')"
# OK

python -c "from src.graph.nodes.task_executor import _dispatch_task; print('OK')"
# OK

python -c "from src.graph.nodes.question_executor import handle_question_answer; print('OK')"
# OK
```

## Integration Points
- **BudgetTracker**: Enforces 2-question limit per thread
- **ConversationModeStore**: Manages ACTIVE/PASSIVE conversation mode
- **TaskPlanStore**: Persists plan state after each operation
- **StatePatch**: Carries answer data with confidence score

## Flow Summary
```
Task detected as question
  -> question_executor_node
    -> Check budget (exhausted? return budget_exhausted)
    -> Record question asked
    -> Set ACTIVE mode
    -> Return question_posted with question data
  -> _execute_task sees question_posted
    -> Set plan BLOCKED
    -> Return to UI for Slack posting

User answers
  -> handle_question_answer
    -> Apply answer to question_task
    -> Check confidence (low? return low_confidence_answer)
    -> Mark task DONE, reset budget
    -> Continue execution via task_executor_node
```

## Notes
- Question tasks route through the same `_execute_task` flow as regular tasks
- Budget check happens before recording the question (prevents exceeding limit)
- Low confidence answers keep task BLOCKED for clarification (doesn't mark DONE)
- State patch value is applied to the state dict before continuing execution
