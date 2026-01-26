---
phase: 39-intent-classification-v2
plan: 05
subsystem: intent
tags: [policy, ambiguity, risk-guard, threshold]

requires:
  - phase: 39-02
    provides: intent_gates with check_risk_guard
  - phase: 39-04
    provides: IntentEnvelope from Stage 2 classifier
provides:
  - Ambiguity policy module (intent_policy.py)
  - Margin-based ambiguity detection (0.15 threshold)
  - Confidence thresholds for risky operations (0.75/0.85)
  - Risk guard integration from Stage 0
  - Target ambiguity detection
  - Unified apply_all_policies function
affects: [39-06, 39-07]

tech-stack:
  added: []
  patterns: [policy-pattern, threshold-guard, chain-of-responsibility]

key-files:
  created: [src/graph/intent_policy.py]
  modified: []

key-decisions:
  - "Policy order: target ambiguity -> risk guard -> margin/confidence"
  - "Risk guard triggers ambiguous for SINGLE, requires_confirm for PLAN"
  - "_convert_to_ambiguous includes original intent + alternatives + safe fallback"

patterns-established:
  - "PolicyConfig dataclass for threshold configuration"
  - "apply_all_policies as single entry point for all policy checks"

issues-created: []

duration: 8min
completed: 2026-01-25
---

# Phase 39 Plan 05: Ambiguity Policy Summary

**Margin-based ambiguity policy with risk guard integration and unified apply_all_policies entry point**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-25T10:30:00Z
- **Completed:** 2026-01-25T10:38:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Created PolicyConfig with configurable thresholds (margin=0.15, confidence_risky=0.75, confidence_destructive=0.85)
- Implemented apply_ambiguity_policy that converts to ambiguous when thresholds not met
- Integrated apply_risk_guard using Stage 0 check_risk_guard from intent_gates
- Added check_target_ambiguity for detecting missing targets on targeted intents
- Created apply_all_policies as unified entry point chaining all policy checks

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ambiguity policy module** - `a085189` (feat)
2. **Task 2: Add policy integration helper** - `b96b16a` (feat)

## Files Created/Modified

- `src/graph/intent_policy.py` - New ambiguity policy module with all policy functions

## Decisions Made

- **Policy application order:** Target ambiguity check runs first (catches missing targets), then risk guard (applies Stage 0 guards), then margin/confidence policy (final threshold check)
- **Risk guard behavior:** For SINGLE envelopes, triggers ambiguous on guard; for PLAN envelopes, sets requires_confirm=True instead
- **Ambiguous conversion:** Includes original intent as first choice, up to 2 alternatives, and always adds "Just discuss" safe fallback (max 4 choices)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Ambiguity policy module ready for integration in Stage 2 orchestrator
- apply_all_policies provides single entry point for plan 06/07
- All thresholds match Phase 39 spec Section 6

---
*Phase: 39-intent-classification-v2*
*Completed: 2026-01-25*
