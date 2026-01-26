---
phase: 42-code-modularization
plan: 06
status: complete
completed_at: 2026-01-26
---

# Plan 42-06 Summary: Split decision_buttons.py

## Objective
Split the 1433-line `decision_buttons.py` monolith into a focused package with logical modules.

## Result
Successfully created `src/slack/handlers/decision_buttons/` package with 4 modules:

| Module | Lines | Purpose |
|--------|-------|---------|
| `approve.py` | 208 | Decision approval handlers and Jira sync |
| `change.py` | 466 | Edit/change handlers and modal submissions |
| `deprecate.py` | 362 | Discard/deprecate handlers and modal submissions |
| `view.py` | 407 | History, view, show/hide details handlers |
| `__init__.py` | 100 | Re-exports and `register_decision_handlers()` |
| **Total** | **1543** | *(includes docstrings and proper separation)* |

## Tasks Completed

1. **Task 1: Create decision_buttons package with approve module**
   - Created `src/slack/handlers/decision_buttons/` directory
   - Extracted `handle_decision_approve` to `approve.py`
   - Created `__init__.py` with initial re-exports

2. **Task 2: Extract change and deprecate handlers**
   - Created `change.py` with edit/change button handlers and modals
   - Created `deprecate.py` with discard/deprecate button handlers and modals

3. **Task 3: Extract view handlers and finalize**
   - Created `view.py` with history, view, and show/hide details handlers
   - Updated `__init__.py` with all re-exports and registration function
   - Deleted original `decision_buttons.py`

## Verification

```bash
# Main import works
python -c "from src.slack.handlers.decision_buttons import register_decision_handlers"
# OK

# All exports available
python -c "from src.slack.handlers.decision_buttons import (
    handle_decision_approve,
    handle_decision_edit,
    handle_decision_change,
    handle_decision_deprecate,
    handle_decision_view,
    register_decision_handlers,
)"
# OK
```

## Commits

- `76047bb`: refactor(42-06): create decision_buttons package with approve module
- `a0ab295`: refactor(42-06): extract change and deprecate handlers
- `a0c5e57`: refactor(42-06): extract view handlers and finalize decision_buttons package

## Notes

- Two modules slightly exceed 400 lines (change.py: 466, view.py: 407) due to comprehensive docstrings and the complexity of modal handlers with impact preview functionality (Phase 41)
- All handlers maintain INVARIANT I2 (Slack = UI, truth-first ordering)
- Original file deleted after all imports verified working
