---
phase: 05-agent-core
plan: 03
status: complete
---

# 05-03 Summary: Validation & Decision Nodes

## What Was Built

1. **Validation node** (`src/graph/nodes/validation.py`)
   - LLM-first validation with rule-based fallback
   - `ValidationReport` model with: is_valid, missing_fields[], conflicts[], suggestions[], quality_score
   - Checks minimum requirements: title + problem + 1 AC
   - Detects constraint conflicts (same key, different values)
   - Calculates quality_score 0-100 for prioritization

2. **Decision node** (`src/graph/nodes/decision.py`)
   - Routes to ASK, PREVIEW, or READY_TO_CREATE
   - `DecisionResult` model with: action, questions[], reason
   - `prioritize_issues()` - conflicts first, then missing fields
   - `batch_questions()` - max 3 questions per batch
   - Smart question generation for common fields (title, problem, AC)
   - `get_decision_action()` helper for graph routing

3. **Updated graph** (`src/graph/graph.py`)
   - Added validation_node and decision_node
   - New edge: validation → decision
   - Conditional routing from decision: ask/preview/ready → END
   - `route_after_decision()` function for conditional edges

## Graph Flow

```
START -> extraction -> should_continue -> validation -> decision -> (ask/preview/ready: END)
         ^                |
         |                v
         +--- loop back --+
```

## Verification

```bash
python -c "from src.graph.nodes import validation_node, decision_node; print('nodes ok')"
# Output: nodes ok

python -c "from src.graph import create_graph; g = create_graph(); print('updated graph ok')"
# Output: updated graph ok
```

## Files Created/Modified

- `src/graph/nodes/validation.py` (created)
- `src/graph/nodes/decision.py` (created)
- `src/graph/nodes/__init__.py` (updated exports)
- `src/graph/graph.py` (updated with full pipeline)

## Ready For

Wave 4 (05-04): Runner integration with Slack handlers.
