---
phase: 39-intent-classification-v2
plan: 04
subsystem: intent
tags: [llm, classification, intent, pydantic, regex]

# Dependency graph
requires:
  - phase: 39-01
    provides: IntentEnvelope schema
  - phase: 39-03
    provides: Stage1Result for mode classification
provides:
  - Stage 2 intent classifier (classify_intent)
  - MODE_INTENTS mapping per SuperMode
  - INTENT_RISK risk levels by intent
  - Deterministic Jira key extraction (extract_jira_keys)
  - Target hints builder (build_target_hints)
affects: [39-intent-classification-v2, intent-routing, graph-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-stage classification: Stage 1 (mode) -> Stage 2 (intent)"
    - "Risk-ordered task sorting in plan envelopes"
    - "Deterministic extraction before LLM classification"

key-files:
  created:
    - src/graph/intent_stage2.py
  modified: []

key-decisions:
  - "MODE_INTENTS maps SuperMode to valid intents (restricts LLM choices)"
  - "INTENT_RISK classifies each intent for safety (SAFE/WRITE/MASS_WRITE/DESTRUCTIVE)"
  - "_build_plan_envelope sorts tasks by risk (safe reads before writes)"
  - "Deterministic Jira key extraction via regex (not LLM)"

patterns-established:
  - "Stage 2 prompt uses structured JSON output schema"
  - "Fallback to ambiguous envelope on any parse/classification error"

issues-created: []

# Metrics
duration: 5min
completed: 2026-01-25
---

# Phase 39 Plan 04: Stage 2 Intent Classifier Summary

**Stage 2 intent extraction with full LLM classification, risk-ordered task decomposition, and deterministic Jira key extraction**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-25T18:15:00Z
- **Completed:** 2026-01-25T18:20:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Stage 2 classifier extracts specific intent within mode from Stage 1
- MODE_INTENTS maps SuperMode to valid intents (BUILD -> DRAFT_REFINE/DRAFT_TRANSFORM/WORKITEM_CREATE, etc.)
- INTENT_RISK classifies each intent by risk level (SAFE, WRITE, MASS_WRITE, DESTRUCTIVE)
- _build_plan_envelope sorts multi-intent tasks by risk (safe reads first)
- Deterministic target extraction via JIRA_KEY_PATTERN regex
- build_target_hints combines anchor-based and message-based targets

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Stage 2 intent classifier** - `8c8cf1b` (feat)
2. **Task 2: Add target extraction helpers** - `ace8674` (feat)

## Files Created/Modified

- `src/graph/intent_stage2.py` - Full Stage 2 classifier with classify_intent(), envelope builders, and target extraction helpers

## Decisions Made

- MODE_INTENTS restricts LLM to valid intents per SuperMode (no cross-mode confusion)
- INTENT_RISK is explicit mapping rather than derived (easier to audit)
- Risk ordering in plans: SAFE(0) < WRITE(1) < MASS_WRITE(2) < DESTRUCTIVE(3)
- Deterministic Jira extraction happens before LLM for reliability

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Stage 2 classifier ready for integration with intent_router_node
- Ready for 39-05-PLAN.md (Integration with graph routing)

---
*Phase: 39-intent-classification-v2*
*Completed: 2026-01-25*
