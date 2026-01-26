---
phase: 44-questions-first-collection-stage
plan: 01
subsystem: intent
tags: [triage, context, signals, gaps, routing]

# Dependency graph
requires:
  - phase: 39-intent-classification-v2
    provides: SuperMode, Intent, PreGateOutput pattern
provides:
  - TriageContext schema for context completeness assessment
  - TriageSignal enum (6 signal types)
  - TriageGap enum (5 gap types)
  - check_triage_needed() gate function
affects: [44-02, 44-03, intent-routing, question-flow]

# Tech tracking
tech-stack:
  added: []
  patterns: [signal-gap-completeness pattern for triage]

key-files:
  created:
    - src/schemas/triage.py
    - src/graph/triage_gate.py
  modified: []

key-decisions:
  - "Completeness threshold 0.7 for fast path determination"
  - "Gap penalties: UNKNOWN_TARGET=0.3 (highest), UNKNOWN_MODE=0.2, AMBIGUOUS_INTENT=0.2"
  - "No LLM calls in triage gate - fully deterministic for speed"

patterns-established:
  - "Signal-gap-completeness pattern: detect positive signals, identify missing gaps, compute score"
  - "TriageContext.from_gaps_and_signals() factory for computed fields"

issues-created: []

# Metrics
duration: 3min
completed: 2026-01-26
---

# Phase 44 Plan 01: Triage Context Schema Summary

**TriageContext schema and check_triage_needed() gate for detecting incomplete context before intent classification**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-26T12:58:00Z
- **Completed:** 2026-01-26T13:01:00Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments

- Created TriageSignal enum with 6 signal types (HAS_DRAFT, HAS_ANCHOR, HAS_JIRA_KEY, HAS_EXPLICIT_MODE, HAS_TOPIC, LOW_CONFIDENCE_MODE)
- Created TriageGap enum with 5 gap types (UNKNOWN_MODE, UNKNOWN_SCOPE, UNKNOWN_TARGET, AMBIGUOUS_INTENT, MISSING_TOPIC)
- Created TriageContext dataclass with signals, gaps, completeness_score, suggested_questions, fast_path
- Created check_triage_needed() gate function that returns TriageContext with computed fields

## Task Commits

Each task was committed atomically:

1. **Task 1: Create TriageContext schema** - `ba5fa6d` (feat)
2. **Task 2: Create triage gate module** - `9553bd5` (feat)

## Files Created/Modified

- `src/schemas/triage.py` - TriageSignal enum, TriageGap enum, TriageContext dataclass with factory method
- `src/graph/triage_gate.py` - detect_signals(), detect_gaps(), compute_completeness(), check_triage_needed()

## Decisions Made

- **Completeness threshold 0.7:** Fast path triggers when completeness >= 0.7, meaning minor gaps don't block routing
- **Gap severity penalties:** UNKNOWN_TARGET (0.3) is most severe since we can't route without knowing what we're working on
- **No LLM calls:** Triage gate is deterministic for speed - pattern matching and state checks only
- **Signal vs Gap design:** Signals indicate what we HAVE, gaps indicate what's MISSING - cleaner than single enum

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- TriageContext and check_triage_needed() ready for integration
- Plan 44-02 can wire triage gate into intent routing flow
- Gap-to-question mapping ready for question generation phase

---
*Phase: 44-questions-first-collection-stage*
*Completed: 2026-01-26*
