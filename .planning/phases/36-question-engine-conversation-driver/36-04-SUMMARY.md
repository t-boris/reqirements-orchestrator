---
phase: 36-question-engine-conversation-driver
plan: 04
status: complete
---

# Plan 36-04: AnswerMapper and BudgetTracker

## Summary
Created AnswerMapper for processing user responses (button clicks and text replies) and BudgetTracker for enforcing question limits per conversation thread.

## Files Created

### src/questions/answer_mapper.py
- **ButtonAnswerMapper**: Deterministic mapping from button clicks to StatePatch
  - `parse_action_id(action_id)` - parse "question_{question_id}_{option_id}"
  - `parse_value(value)` - parse "{question_id}:{option_id}:{encoded_value}"
  - `map_click(action_id, value, question_task)` - returns StatePatch with confidence=1.0

- **TextAnswerMapper**: LLM-based parsing for text replies
  - `PARSE_PROMPT` - template for LLM parsing
  - `FIELD_SCHEMAS` - dict mapping fields to expected formats (scope, generation_mode, etc.)
  - `async map_text(text, expected_field, question_task, llm)` - returns StatePatch with LLM confidence
  - `_parse_llm_response(response)` - JSON parsing helper with fallback

- **AnswerMapper**: Unified facade class
  - `map_button_click(action_id, value, question_task)` - deterministic routing
  - `async map_text_reply(text, question_task, llm)` - LLM-parsed routing

- **Helper functions**:
  - `encode_button_action_id(question_id, option_id)` - create action_id
  - `encode_button_value(question_id, option_id, value)` - create value string

### src/questions/budget_tracker.py
- **BudgetExhaustedAction** enum:
  - `PROCEED_WITH_GAPS` - continue with incomplete info
  - `WAIT_FOR_INPUT` - stay in thread, wait for user
  - `CANCEL` - cancel the operation

- **BudgetTracker** class:
  - `can_ask(channel_id, thread_ts)` - returns True if under budget
  - `record_question_asked(channel_id, thread_ts)` - increment counter
  - `record_answer_received(channel_id, thread_ts)` - reset counter
  - `get_remaining(channel_id, thread_ts)` - remaining questions before limit
  - `is_exhausted(channel_id, thread_ts)` - True if at budget limit

### src/questions/__init__.py
Exports all public classes and functions:
- AnswerMapper, ButtonAnswerMapper, TextAnswerMapper
- encode_button_action_id, encode_button_value
- BudgetExhaustedAction, BudgetTracker

## Verification Results

All verification commands passed:
```
$ python -c "from src.questions.answer_mapper import ButtonAnswerMapper; q, o, v = ButtonAnswerMapper.parse_value('q1:opt1:val'); print(q, o, v)"
q1 opt1 val

$ python -c "from src.questions.answer_mapper import AnswerMapper, TextAnswerMapper; print(TextAnswerMapper.FIELD_SCHEMAS.get('scope'))"
Options: SINGLE, EPICS_ONLY, FULL_PLAN

$ python -c "from src.questions.budget_tracker import BudgetTracker, BudgetExhaustedAction; print(BudgetExhaustedAction.PROCEED_WITH_GAPS)"
BudgetExhaustedAction.PROCEED_WITH_GAPS
```

## Success Criteria Met

- [x] ButtonAnswerMapper.map_click returns StatePatch with confidence=1.0
- [x] TextAnswerMapper.map_text is async and returns confidence-scored patch
- [x] AnswerMapper facade routes correctly to appropriate mapper
- [x] BudgetTracker.can_ask returns False after QUESTION_BUDGET reached
- [x] BudgetExhaustedAction enum has 3 choices
- [x] All components integrate with ConversationModeStore

## Dependencies Used

- `src/schemas/state_patch.py` - StatePatch, AnswerSource, create_button_patch
- `src/schemas/conversation_mode.py` - QUESTION_BUDGET constant (=2)
- `src/db/conversation_mode_store.py` - ConversationModeStore for budget state
- `src/schemas/question.py` - QuestionTask model with options
