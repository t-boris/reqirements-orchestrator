---
phase: 03-intent-modes
plan: 03
subsystem: intent
tags: [llm, instructor, pydantic, intent-classification, routing]

# Dependency graph
requires:
  - phase: 03-01
    provides: LLM client with structured output (Instructor + LiteLLM)
  - phase: 03-02
    provides: PreGates for deterministic routing
provides:
  - LLM Router with two-stage classification
  - Confidence thresholds with safe CONVERSE fallback
  - Intent classification prompts
affects: [safety-evaluator, mode-handlers, event-handlers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-stage routing: PreGates (deterministic) -> LLM Router (classification)"
    - "Confidence threshold pattern: 0.7 base, 0.85 for side-effect modes"
    - "Safe fallback: CONVERSE on low confidence or LLM errors"

key-files:
  created:
    - src/intent/prompts.py
    - src/intent/router.py
  modified:
    - src/intent/__init__.py

key-decisions:
  - "0.7 base confidence threshold per RESEARCH.md recommendation"
  - "0.85 threshold for CREATE/MODIFY (side-effect modes require higher bar)"
  - "PreGate APPROVAL maps to MODIFY mode (changing entity state)"
  - "All other PreGate results map to CONVERSE (handled elsewhere)"

patterns-established:
  - "Pattern: RouterContext dataclass for routing state"
  - "Pattern: _apply_confidence_thresholds for safe fallback logic"

issues-created: []

# Metrics
duration: 2min
completed: 2026-02-02
---

# Phase 03 Plan 03: LLM Router Summary

**Two-stage intent router with structured LLM output, confidence thresholds (0.7/0.85), and safe CONVERSE fallback**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-02
- **Completed:** 2026-02-02
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Created intent classification prompts per BOT_DESIGN.md specification
- Implemented LLM Router using Instructor for structured output
- Added two-stage routing: PreGates (deterministic) then LLM classification
- Implemented confidence thresholds with safe CONVERSE fallback

## Task Commits

Each task was committed atomically:

1. **Task 1: Create intent classification prompts** - `dc5b425` (feat)
2. **Task 2: Implement LLM Router** - `bb88827` (feat)
3. **Task 3: Update intent module exports** - already done (exports existed from 03-04)

## Files Created/Modified

- `src/intent/prompts.py` - Classification prompts (system + user template)
- `src/intent/router.py` - LLM Router with classify_intent, RouterContext, confidence thresholds
- `src/intent/__init__.py` - Module exports (already included router functions)

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| 0.7 base confidence threshold | Per RESEARCH.md recommendation - conservative default |
| 0.85 for CREATE/MODIFY | Side-effect modes need higher confidence to prevent unwanted actions |
| APPROVAL PreGate maps to MODIFY | Approvals change entity state (lifecycle transition) |
| Other PreGates map to CONVERSE | Commands, actions, processes handled by dedicated handlers |

## Deviations from Plan

Task 3 (Update intent module exports) was already completed - the `__init__.py` file was updated by a subsequent plan (03-04) that ran before this plan was executed. The exports were already in place, so no changes were needed.

**Total deviations:** 1 (execution order)
**Impact on plan:** None - the required functionality was already present

## Issues Encountered

None - all verifications passed

## Next Phase Readiness

- LLM Router complete with safe defaults
- Ready for Safety Evaluator integration (03-04)
- classify_intent function available for event handlers to use

---
*Phase: 03-intent-modes*
*Completed: 2026-02-02*
