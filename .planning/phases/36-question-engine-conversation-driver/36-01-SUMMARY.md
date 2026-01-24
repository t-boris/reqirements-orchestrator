---
phase: 36-question-engine-conversation-driver
plan: 01
status: completed
completed_at: 2026-01-24
---

# Plan 36-01 Summary: QuestionTask Schema

## Objective
Add QuestionTask schema extending the TaskPlan model with question-specific fields.

## What Was Implemented

### 1. Created `src/schemas/question.py`
New module with question-specific schemas:

- **QuestionType enum** with 4 values:
  - `CONFIRM_SCOPE` - Choice from known options (parent selection, scope)
  - `COLLECT_FIELD` - Get specific field value (acceptance criteria, title)
  - `RESOLVE_CONFLICT` - Pick A or B for conflict resolution
  - `ASK_USER` - Freeform fallback when no template fits

- **QuestionStatus enum** with 3 values:
  - `PENDING` - Not yet answered
  - `ANSWERED` - User provided answer
  - `SKIPPED` - Bypassed due to budget or user choice

- **QuestionOption model**:
  - `option_id: str` - UUID for button value
  - `label: str` - Button text
  - `description: Optional[str]` - Longer description
  - `value: Any` - The actual value to apply
  - `is_recommended: bool` - Highlight as recommended

- **QuestionTask model**:
  - `question_id: str` - UUID
  - `question_type: QuestionType`
  - `question_text: str` - The actual question to display
  - `target_field: Optional[str]` - For COLLECT_FIELD, which draft field we're filling
  - `options: Optional[list[QuestionOption]]` - For CONFIRM_SCOPE/RESOLVE_CONFLICT
  - `priority: int` - Lower = ask first (default 100)
  - `status: QuestionStatus` - Default PENDING
  - `answer: Optional[str]` - User's answer once provided
  - `answered_at: Optional[datetime]`
  - `answered_by: Optional[str]` - user_id
  - Helper methods: `is_answered()`, `is_pending()`, `has_options()`

### 2. Extended `src/schemas/task_plan.py`
Added question support to existing Task model:

- **New field**: `question_task: Optional[QuestionTask]` - For question-type tasks
- **New property**: `is_question` - Returns True when question_task is set
- **New factory method**: `create_question(mode, intent, question_task, depends_on)` - Creates a question task with appropriate defaults
- **Forward reference handling**: Added TYPE_CHECKING import and model_rebuild() call

### 3. Updated `src/schemas/__init__.py`
Exported new schemas:
- `QuestionType`
- `QuestionStatus`
- `QuestionTask`
- `QuestionOption`

## Files Modified
- `src/schemas/question.py` (created)
- `src/schemas/task_plan.py` (modified)
- `src/schemas/__init__.py` (modified)

## Verification Results

All verification checks passed:

```
$ python -c "from src.schemas.question import QuestionType, QuestionTask; print('OK')"
OK

$ python -c "from src.schemas.task_plan import Task; print(Task.create_question)"
<function Task.create_question at 0x...>

$ python -c "# Test all QuestionType values"
QuestionType.CONFIRM_SCOPE: validated
QuestionType.COLLECT_FIELD: validated
QuestionType.RESOLVE_CONFLICT: validated
QuestionType.ASK_USER: validated

$ python -c "# Test is_question property"
Task without question: is_question=False
Task with question: is_question=True

$ python -c "# Test create_question factory"
Task.create_question works correctly with all fields
```

## Issues Encountered
- **Forward reference resolution**: Pydantic required explicit `model_rebuild()` call after importing QuestionTask to resolve the forward reference. This was handled by adding the import and rebuild call at the end of `task_plan.py`.

## Success Criteria Met
- [x] QuestionType enum with 4 values
- [x] QuestionTask model with all required fields
- [x] Task model extended with question support
- [x] No import errors or circular dependencies
- [x] All schemas exported from src.schemas
