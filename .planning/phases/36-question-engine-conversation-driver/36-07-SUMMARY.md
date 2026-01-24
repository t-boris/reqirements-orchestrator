# Plan 36-07 Summary: Question UI blocks and button handlers

## Status: COMPLETED

## What Was Built

### 1. Question UI Blocks (`src/slack/blocks/question.py`)
Created Slack block builders for the question UI:

- **`build_question_blocks(question_data, plan_id, plan_version)`**: Builds conversation-like question display with:
  - Question text as a prominent section
  - Option buttons with version-bound values for idempotency
  - Recommended options highlighted with primary style
  - Option descriptions in context block (max 4)
  - "Reply in thread" hint for text response questions
  - "Other..." button for CONFIRM_SCOPE questions

- **`build_budget_exhausted_blocks(pending_fields, plan_id)`**: Builds UI for when question limit is reached:
  - Header explaining the limit
  - List of still-missing fields
  - Three action buttons: [Proceed with gaps] [Wait for input] [Cancel]

- **`build_clarification_blocks(original_question, reason, question_id, plan_id, plan_version)`**: Builds clarification request for low-confidence answers

### 2. Question Button Handlers (`src/slack/handlers/question.py`)
Created handlers registered via `register_question_handlers(app)`:

- **`handle_question_button`** (regex pattern `^question_.*`):
  - Parses value to extract plan_id, question_id, version, option_id
  - Version check against current plan version (rejects stale clicks)
  - Special handling for "Other" button (prompts text reply)
  - Maps button click to StatePatch using AnswerMapper
  - Calls `handle_question_answer` from question_executor
  - Posts follow-up question or completion message

- **`handle_budget_action`** (regex pattern `^budget_(proceed|wait|cancel)_.*`):
  - "Proceed with gaps": Skips pending questions, resumes plan
  - "Wait for input": Posts waiting message
  - "Cancel": Cancels entire TaskPlan

### 3. Handler Registration
- Added `register_question_handlers` to `src/slack/router.py`
- Added export to `src/slack/handlers/__init__.py`
- All imports verified to work without circular dependencies

## Technical Decisions

1. **Deferred imports in `_process_button_answer()`**: To avoid circular import between `src.slack.handlers.question` -> `src.graph.nodes.question_executor` -> `src.questions.budget_tracker`, the imports of `handle_question_answer` and `AnswerMapper` are done inside the async function.

2. **Version binding format**: Button values encode `{plan_id}:{question_id}:{version}:{option_id}:{encoded_value}` for full idempotency checking.

3. **Async pattern**: Uses `_run_async()` from core handlers to run async code from Slack's sync callback context, consistent with other handlers in the codebase.

## Files Modified
- `src/slack/blocks/question.py` (new)
- `src/slack/handlers/question.py` (new)
- `src/slack/handlers/__init__.py` (added export)
- `src/slack/router.py` (added registration)

## Verification
```bash
# Build blocks
python -c "from src.slack.blocks.question import build_question_blocks; b = build_question_blocks({'question_text': 'Test?', 'options': []}, 'p1', 1); print(len(b))"
# Output: 2

# Import handlers
python -c "from src.slack.handlers.question import register_question_handlers; from src.slack.blocks.question import build_question_blocks; print('OK')"
# Output: OK

# Full test
python -c "
from src.slack.blocks.question import build_question_blocks, build_budget_exhausted_blocks
q_data = {'question_id': 'q1', 'question_type': 'CONFIRM_SCOPE', 'question_text': 'What scope?', 'options': [{'option_id': 'opt1', 'label': 'Option 1', 'value': 'v1', 'is_recommended': True}]}
print(f'Question blocks: {len(build_question_blocks(q_data, \"p1\", 1))}')
print(f'Budget blocks: {len(build_budget_exhausted_blocks([\"field1\"], \"p1\"))}')
"
# Output: Question blocks: 3, Budget blocks: 3
```

## Next Steps
Plan 36-08 (next wave): Wire everything together with integration in the main dispatch flow.
