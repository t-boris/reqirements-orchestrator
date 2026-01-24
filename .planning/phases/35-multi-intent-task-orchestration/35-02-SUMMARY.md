---
phase: 35-multi-intent-task-orchestration
plan: 02
subsystem: intent
tags: [multi-intent, llm, classification, taskplan]

# Dependency graph
requires:
  - phase: 31-architecture-hardening
    provides: SuperMode enum for user-facing simplicity
provides:
  - TaskPlanProposal schema for multi-intent classification
  - has_multi_intent_markers() helper function
  - should_use_multi_intent_classification() heuristics
  - Multi-intent LLM classification support
affects: [35-03, 35-04, 35-05, task-orchestration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Two-stage intent classification (single-intent first, multi-intent if triggered)
    - Conjunction detection for compound requests

key-files:
  created: []
  modified:
    - src/schemas/intent.py
    - src/graph/intent.py

key-decisions:
  - "Multi-intent triggered by: conjunctions, low confidence (<0.7), multiple action verbs"
  - "TaskPlanProposal wraps multiple TaskProposals with dependency tracking"
  - "Backwards compatible via return_proposal=False default and to_single_intent()"

patterns-established:
  - "Two-stage classification: quick single-intent, then re-classify if multi-intent signals"
  - "MULTI_INTENT_MARKERS for conjunction detection"
  - "ACTION_VERBS for multi-verb heuristic"

issues-created: []

# Metrics
duration: 12min
completed: 2026-01-24
---

# Phase 35 Plan 02: Multi-Intent Classification Summary

**TaskPlanProposal schema with LLM multi-intent detection and heuristics for compound requests**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-24T06:45:00Z
- **Completed:** 2026-01-24T06:57:00Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- TaskPlanProposal and TaskProposal models for multi-intent classification
- Multi-intent LLM prompt that returns JSON array of intents
- Detection heuristics (conjunctions, low confidence, multiple verbs)
- Backwards compatible classify_intent() with return_proposal parameter

## Task Commits

Each task was committed atomically:

1. **Task 1: Add TaskPlanProposal schema** - `bcd608a` (feat)
2. **Task 2: Update LLM prompt for multi-intent** - `957d8f7` (feat)
3. **Task 3: Add multi-intent detection heuristics** - `d7d32a7` (feat)

## Files Created/Modified

- `src/schemas/intent.py` - Added TaskProposal, TaskPlanProposal, MULTI_INTENT_MARKERS, has_multi_intent_markers()
- `src/graph/intent.py` - Added _llm_classify_multi_intent(), should_use_multi_intent_classification(), updated classify_intent()

## Decisions Made

- **Two-stage classification**: First do quick single-intent, then re-classify with multi-intent prompt if signals detected
- **Multi-intent signals**: Conjunctions ("and", "also", "plus"), low confidence (<0.7), multiple action verbs (>=2)
- **Backwards compatibility**: return_proposal=False by default, to_single_intent() method for legacy callers
- **JSON output format**: Multi-intent LLM returns JSON array with intent, confidence, title, params per task

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- TaskPlanProposal schema ready for TaskPlan persistence (35-03)
- classify_intent() ready to return proposals for task decomposer
- All verification criteria met:
  - TaskPlanProposal model works with multiple tasks
  - Single-intent messages still work (is_multi_intent=False)
  - "create stories and check duplicates" would return 2 tasks
  - Low confidence triggers multi-intent re-classification
  - to_single_intent() works for backwards compatibility

---
*Phase: 35-multi-intent-task-orchestration*
*Completed: 2026-01-24*
