---
phase: 13-intent-router
plan: 01
subsystem: graph
tags: [intent-classification, langgraph, pydantic, llm, routing]

# Dependency graph
requires:
  - phase: 12-onboarding-ux
    provides: classify_hesitation pattern for LLM-based classification
provides:
  - IntentType enum (TICKET, REVIEW, DISCUSSION)
  - IntentResult Pydantic model for classification results
  - intent_router_node for LangGraph
  - route_after_intent for flow routing
affects: [13-02 (review flow), 13-03 (discussion flow), 13-04 (scope gate)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pattern-matching-first with LLM fallback for intent classification"
    - "Negation patterns checked before positive patterns"

key-files:
  created:
    - src/graph/intent.py
  modified:
    - src/schemas/state.py
    - src/graph/graph.py

key-decisions:
  - "Negation patterns have highest priority to handle 'don't create ticket' correctly"
  - "REVIEW/DISCUSSION flows go to END as placeholders for Plans 02/03"

patterns-established:
  - "Pattern-matching-first: Check explicit patterns before LLM call for performance"
  - "Negation priority: Check negation patterns before positive patterns"

issues-created: []

# Metrics
duration: 12min
completed: 2026-01-15
---

# Phase 13 Plan 01: Intent Router Core Summary

**IntentRouter node with pattern-matching-first classification, routing messages to TICKET/REVIEW/DISCUSSION flows before extraction**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-15T17:10:00Z
- **Completed:** 2026-01-15T17:22:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- IntentType enum: TICKET, REVIEW, DISCUSSION
- IntentResult Pydantic model with confidence, persona_hint, topic, reasons
- Explicit override patterns (checked before LLM, force confidence=1.0)
- Negation patterns checked first to handle "don't create ticket" correctly
- LLM classification for ambiguous cases
- intent_router_node as new graph entry point
- Flow routing: ticket_flow (extraction), review_flow (END), discussion_flow (END)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create IntentResult schema and IntentRouter node** - `1e30aa7` (feat)
2. **Task 2: Extend AgentState with intent fields** - `d0c1125` (feat)
3. **Task 3: Integrate IntentRouter as graph entry point** - `6b3147e` (feat)

## Files Created/Modified

- `src/graph/intent.py` - IntentRouter node with pattern matching and LLM fallback
- `src/schemas/state.py` - Added intent_result field to AgentState
- `src/graph/graph.py` - Integrated intent_router as entry point, added flow routing

## Decisions Made

1. **Negation patterns have highest priority** - Patterns like "don't create ticket" must be checked before positive patterns like "create ticket" to correctly route to REVIEW flow instead of TICKET flow.

2. **REVIEW/DISCUSSION flows go to END** - These are placeholder destinations. Plan 02 will add the review node, Plan 03 will add the discussion node.

3. **Pattern-matching-first approach** - Explicit patterns are checked before LLM call to avoid unnecessary LLM calls for obvious cases (performance optimization).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed negation pattern priority**
- **Found during:** Task 3 verification
- **Issue:** "don't create a ticket" was matching TICKET pattern before REVIEW negation pattern
- **Fix:** Added separate NEGATION_PATTERNS list checked before TICKET_PATTERNS
- **Files modified:** src/graph/intent.py
- **Verification:** Comprehensive pattern tests pass (22/22)
- **Committed in:** 6b3147e (part of Task 3 commit via amend)

---

**Total deviations:** 1 auto-fixed (bug fix for pattern priority)
**Impact on plan:** Essential fix for correct intent classification. No scope creep.

## Issues Encountered

None - all tasks completed successfully.

## Next Phase Readiness

- IntentRouter correctly classifies messages into TICKET/REVIEW/DISCUSSION
- Explicit patterns work with persona hints (security, architect, pm)
- LLM fallback handles ambiguous cases
- Ready for Plan 02: Review Flow implementation

---
*Phase: 13-intent-router*
*Completed: 2026-01-15*
