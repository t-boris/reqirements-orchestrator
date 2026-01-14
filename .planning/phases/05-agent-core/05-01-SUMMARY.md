---
phase: 05-agent-core
plan: 01
status: complete
---

# 05-01 Summary: State & Draft Schemas

## What Was Built

1. **TicketDraft schema** (`src/schemas/draft.py`)
   - Rich draft with all fields: title, problem, proposed_solution, acceptance_criteria[], constraints[], dependencies[], risks[]
   - `DraftConstraint` with key/value/status tracking
   - `EvidenceLink` for Slack message traceability
   - `is_preview_ready()` - checks minimum viable (title + problem + 1 AC)
   - `get_missing_for_preview()` - lists missing fields
   - `patch(**updates)` - incremental updates with version tracking
   - `add_evidence()` - adds traceability links

2. **Enhanced AgentState** (`src/schemas/state.py`)
   - Added `AgentPhase` enum: COLLECTING → VALIDATING → AWAITING_USER → READY_TO_CREATE → CREATED
   - Changed draft type to `Optional[TicketDraft]`
   - Added `step_count` for loop protection (max_steps=10)
   - Added `state_version` and `last_updated_at` for race detection
   - Added `validation_report` and `decision_result` dicts
   - Kept legacy fields for backwards compatibility

3. **Updated exports** (`src/schemas/__init__.py`)
   - Exports: TicketDraft, DraftConstraint, ConstraintStatus, EvidenceLink, AgentState, AgentPhase

## Verification

```bash
python -c "from src.schemas import TicketDraft, AgentState, AgentPhase; d = TicketDraft(); print('draft ok, is_preview_ready:', d.is_preview_ready())"
# Output: draft ok, is_preview_ready: False
```

## Files Modified

- `src/schemas/draft.py` (created)
- `src/schemas/state.py` (enhanced)
- `src/schemas/__init__.py` (updated exports)

## Ready For

Wave 2 (05-02): Graph & Extraction node can now use TicketDraft and AgentPhase.
