---
phase: 36-question-engine-conversation-driver
plan: 06
status: completed
completed_at: 2026-01-24
---

# Plan 36-06: Mode Integration into Dispatch - Summary

## Objective
Integrate Active/Passive mode transitions and budget exhausted handling into dispatch.

## Files Modified
- `src/questions/mode_manager.py` (created)
- `src/slack/handlers/dispatch.py` (modified)
- `src/questions/__init__.py` (modified)

## Changes Made

### Task 1: Created ModeManager for centralized mode handling
Created new file `src/questions/mode_manager.py` with:

1. **`ModeManager` class**
   - `__init__(store: ConversationModeStore)` - accepts store dependency
   - `check_and_activate(channel_id, thread_ts, reason)` - transitions to ACTIVE if valid reason, returns True if transitioned
   - `check_and_deactivate(channel_id, thread_ts, reason)` - transitions to PASSIVE if valid reason, returns True if transitioned
   - `check_timeout(channel_id, thread_ts)` - deactivates if >10min since last activity, returns True if timed out
   - `is_active(channel_id, thread_ts)` - returns True if currently in ACTIVE mode
   - `get_state(channel_id, thread_ts)` - returns ConversationModeState
   - `record_activity(channel_id, thread_ts)` - updates last_activity timestamp

2. **`detect_activation_reason(message, bot_user_id, is_command)`**
   - Returns `ModeTransitionReason.COMMAND` if is_command=True
   - Returns `ModeTransitionReason.MENTION` if message contains `<@{bot_user_id}>`
   - Returns None otherwise

3. **`MODE_TIMEOUT_MINUTES = 10`** constant

### Task 2: Integrated mode transitions into dispatch
Modified `src/slack/handlers/dispatch.py`:

1. **Added imports**
   ```python
   from src.questions.mode_manager import ModeManager, detect_activation_reason
   from src.db.conversation_mode_store import ConversationModeStore
   from src.schemas.conversation_mode import ModeTransitionReason
   ```

2. **Added new action handlers in `_dispatch_result`**
   - `"question_posted"` -> calls `_handle_question_posted()`
   - `"budget_exhausted"` -> calls `_handle_budget_exhausted()`
   - `"task_rejected"` -> calls `_handle_task_rejected()`

3. **Created handler functions**
   - `_handle_question_posted(client, result, identity)` - posts question UI
   - `_handle_budget_exhausted(client, result, identity)` - posts partial preview
   - `_post_question_ui(client, channel_id, thread_ts, question_data, plan_id, plan_version)` - stub that imports from Plan 07 or falls back to simple text
   - `_post_budget_exhausted_ui(client, channel_id, thread_ts, pending_fields, plan_id)` - stub with fallback

### Task 3: Handle plan completion mode transition
Modified `src/slack/handlers/dispatch.py`:

1. **Updated `_handle_task_plan_complete`**
   - Added mode deactivation with `ModeTransitionReason.PLAN_COMPLETE`
   - Uses `get_connection()` context manager for database access

2. **Created `_handle_task_rejected(client, result, identity)`**
   - Checks if task_plan.status == CANCELED
   - If canceled: deactivates mode with `ModeTransitionReason.USER_CANCEL`, posts cancel message
   - If not canceled: posts rejection acknowledgment, plan continues

3. **Updated `src/questions/__init__.py` exports**
   - Added `ModeManager`, `detect_activation_reason`, `MODE_TIMEOUT_MINUTES`

## Verification
All verification commands passed:
```bash
python -c "from src.questions.mode_manager import ModeManager, detect_activation_reason; print('OK')"
# OK

python -c "from src.questions import ModeManager; print('OK')"
# OK

python -c "from src.slack.handlers.dispatch import _post_question_ui; print('OK')"
# OK

python -m py_compile src/slack/handlers/dispatch.py
# Syntax OK
```

## Integration Points
- **ConversationModeStore**: Persists mode state (channel_id, thread_ts, mode, timestamps)
- **ModeManager**: Central orchestrator for mode transitions with validation
- **Dispatch handlers**: Route question_posted, budget_exhausted, task_rejected actions
- **Plan 07 dependency**: Question UI blocks module (graceful fallback to simple text)

## Flow Summary
```
Plan completes (all tasks DONE)
  -> _handle_task_plan_complete
    -> ModeManager.check_and_deactivate(PLAN_COMPLETE)
    -> Mode transitions ACTIVE -> PASSIVE
    -> Post completion summary

Task rejected by user
  -> _handle_task_rejected
    -> If plan CANCELED: deactivate with USER_CANCEL
    -> Post appropriate message

Question posted (from question_executor)
  -> _handle_question_posted
    -> _post_question_ui (with Plan 07 fallback)
    -> Logs question details

Budget exhausted
  -> _handle_budget_exhausted
    -> _post_budget_exhausted_ui
    -> Shows pending fields, offers to proceed
```

## Notes
- Stub functions gracefully handle missing Plan 07 module with fallback text messages
- Mode deactivation is wrapped in try/except to prevent blocking completion flow
- All handlers follow existing dispatch pattern with logging
- detect_activation_reason supports both @mention and /command triggers
