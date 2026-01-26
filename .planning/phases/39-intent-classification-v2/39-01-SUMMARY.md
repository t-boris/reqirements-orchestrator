---
phase: 39-intent-classification-v2
plan: 01
subsystem: intent
tags: [pydantic, schemas, classification, intent]

# Dependency graph
requires:
  - phase: 35-multi-intent-task-orchestration
    provides: TaskPlanProposal (being replaced)
provides:
  - IntentEnvelope unified output format
  - EnvelopeKind enum (single/plan/ambiguous)
  - RiskLevel enum for safety classification
  - TargetReference for explicit target tracking
affects: [39-intent-classification-v2, intent-routing, dispatch]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Factory methods for envelope construction"
    - "Risk-based confirmation requirements"

key-files:
  created:
    - src/schemas/intent_envelope.py
  modified:
    - src/schemas/__init__.py

key-decisions:
  - "RiskLevel uses enum ordering for max calculation in plan factory"
  - "to_legacy_intent_result() enables gradual migration"

patterns-established:
  - "IntentEnvelope.single/plan/ambiguous() factories for clean construction"

issues-created: []

# Metrics
duration: 2min
completed: 2026-01-26
---

# Phase 39 Plan 01: IntentEnvelope Schema Summary

**Unified IntentEnvelope format with single/plan/ambiguous kinds, confidence + margin metrics, and backward-compatible legacy conversion**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-26T00:09:04Z
- **Completed:** 2026-01-26T00:10:42Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- IntentEnvelope with kind: single/plan/ambiguous for unified classification output
- RiskLevel enum (safe/write/mass_write/destructive) for safety classification
- TargetReference for explicit target tracking (jira_key, decision_id, workitem_id)
- Factory methods for clean construction: single(), plan(), ambiguous()
- Backward compatibility via to_legacy_intent_result()

## Task Commits

Each task was committed atomically:

1. **Task 1: Create IntentEnvelope schema** - `d8f8229` (feat)
2. **Task 2: Export from schemas module** - `1b64676` (feat)

## Files Created/Modified

- `src/schemas/intent_envelope.py` - Unified IntentEnvelope model with factories and legacy conversion
- `src/schemas/__init__.py` - Export IntentEnvelope and related types

## Decisions Made

- RiskLevel uses explicit list ordering for max calculation in plan factory (not .value comparison since string enums don't have natural ordering)
- to_legacy_intent_result() enables gradual migration from IntentResult to IntentEnvelope

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- IntentEnvelope schema ready for Stage 1/2 classifiers
- Ready for 39-02-PLAN.md (Stage 0 pre-gates)

---
*Phase: 39-intent-classification-v2*
*Completed: 2026-01-26*
