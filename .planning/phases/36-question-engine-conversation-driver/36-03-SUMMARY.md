# Plan 36-03 Summary: QuestionCatalog with Hybrid Generators

## Status: COMPLETED

## What Was Built

Created the QuestionCatalog module with hybrid question generators supporting both template-based and LLM-based question generation.

### Files Created/Modified

1. **src/questions/catalog.py** (new)
   - `ScopeQuestionTemplates` class with:
     - `parent_selection(parent_key, parent_summary)` - Confirms story creation under specific Epic
     - `draft_scope(current_scope)` - Selects scope level (SINGLE, EPIC, FULL)
     - `generation_mode()` - Chooses story generation approach
   - `ConflictQuestionTemplates` class with:
     - `field_conflict(field, local_value, remote_value)` - Resolves sync conflicts
   - `FieldQuestionGenerator` class with:
     - `FIELD_PROMPTS` dict with prompts for acceptance_criteria, title, problem, proposed_solution, description, priority, story_points, assignee, labels
     - `async generate(field, draft_context, llm)` - LLM-based question generation
     - `_build_prompt(field, context)` - Builds field-specific prompts
     - `_field_question_cache` - Caching for repeated field questions
   - `QuestionCatalog` facade class with:
     - `confirm_scope(context, template)` - Template-based scope questions
     - `async collect_field(field, draft_context, llm)` - LLM-based field collection
     - `resolve_conflict(field, local_value, remote_value)` - Template-based conflict resolution
     - `async ask_user(context, llm)` - LLM fallback for freeform questions

2. **src/questions/__init__.py** (updated)
   - Added exports for QuestionCatalog, ScopeQuestionTemplates, ConflictQuestionTemplates, FieldQuestionGenerator

## Verification Results

```
1. parent_selection: confirm_scope, options=3
2. draft_scope: confirm_scope, options=3
3. field_conflict: resolve_conflict, options=2
4. resolve_conflict: resolve_conflict
5. collect_field is async: True
6. ask_user is async: True
```

All verification tests passed.

## Architecture

The QuestionCatalog provides a hybrid approach:

| Question Type | Generator | Rationale |
|--------------|-----------|-----------|
| CONFIRM_SCOPE | Templates | Known patterns, deterministic UI |
| COLLECT_FIELD | LLM | Natural, context-aware questions |
| RESOLVE_CONFLICT | Templates | Binary choice, clear presentation |
| ASK_USER | LLM | Fallback for unknown patterns |

## Integration Points

- Uses `QuestionTask`, `QuestionType`, `QuestionOption` from `src/schemas/question.py`
- Uses `get_llm()` from `src/llm` for LLM-based generation
- Exports available via `from src.questions import QuestionCatalog`

## Dependencies Satisfied

- Plan 36-01 (QuestionTask schema) - Used for all returned questions
- Plan 36-02 (AnswerMapper, BudgetTracker) - Integrated in __init__.py exports

## Ready for Next Plans

Plan 36-04 (QuestionQueue) can now use:
- `QuestionCatalog.confirm_scope()` for scope confirmation
- `QuestionCatalog.collect_field()` for field collection
- `QuestionCatalog.resolve_conflict()` for sync conflicts
- `QuestionCatalog.ask_user()` for freeform fallback
