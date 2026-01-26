---
phase: 39-intent-classification-v2
plan: 06
subsystem: graph
tags: [intent, router, langraph, pipeline, classification]

# Dependency graph
requires:
  - phase: 39-intent-classification-v2
    provides: IntentEnvelope, intent_gates, intent_stage1, intent_stage2, intent_policy
provides:
  - Unified intent router orchestrating all classification stages
  - RouterInput/RouterResult dataclasses for clean API
  - route_after_intent for LangGraph conditional edges
  - is_terminal_intent for terminal detection
  - intent_router_node for LangGraph integration
affects: [graph, dispatch, handlers]

# Tech tracking
tech-stack:
  added: []
  patterns: [stage-orchestration, dataclass-input-output, conditional-routing]

key-files:
  created:
    - src/graph/intent_router.py
  modified: []

key-decisions:
  - "route_intent() orchestrates Stage 0 -> 1 -> 2 -> Policy in sequence"
  - "Stage 0 bypass creates deterministic envelope with confidence=1.0"
  - "Stage 0 constraints boost priority modes by 0.2 score"
  - "Context is built using ContextSpec.for_extraction() when channel+thread available"
  - "route_after_intent routes by envelope kind then by mode/intent"
  - "Terminal intents are DISCUSSION and META (CHAT mode)"

patterns-established:
  - "RouterInput/RouterResult dataclasses for clean function signatures"
  - "Pipeline orchestration with bypass, constrain, and pass gate results"
  - "intent_router_node as LangGraph integration point with backward compatibility"

issues-created: []

# Metrics
duration: 8min
completed: 2026-01-25
---

# Phase 39 Plan 06: Unified Intent Router Summary

**Unified intent router orchestrating Stage 0 -> Stage 1 -> Stage 2 -> Policy pipeline with LangGraph integration**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-25T15:30:00Z
- **Completed:** 2026-01-25T15:38:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Created unified intent router at src/graph/intent_router.py
- Implemented full pipeline: Stage 0 pre-gates -> Stage 1 mode classification -> Stage 2 intent extraction -> Policy application
- Added RouterInput/RouterResult dataclasses for clean API boundaries
- Implemented route_after_intent() for LangGraph conditional routing
- Added is_terminal_intent() for terminal intent detection
- Backward compatibility maintained via to_legacy_intent_result()

## Task Commits

Each task was committed atomically:

1. **Task 1: Create unified intent router** - `179692f` (feat)
2. **Task 2: Add route_after_intent helper** - `d2565a3` (feat)

## Files Created/Modified

- `src/graph/intent_router.py` - Unified intent router with full pipeline orchestration and LangGraph integration

## Decisions Made

- route_intent() orchestrates all stages sequentially: Stage 0 -> 1 -> 2 -> Policy
- Stage 0 BYPASS creates envelope with confidence=1.0 and margin=1.0 (deterministic)
- Stage 0 CONSTRAIN boosts priority modes by 0.2 score then re-sorts candidates
- Context built using ContextSpec.for_extraction() (requires both channel_id and thread_ts)
- route_after_intent returns node names: ask_user_choice, task_decomposer, terminal_response, build_handler, review_handler, decision_handler, operate_handler, default_handler
- Terminal intents identified as DISCUSSION and META (both in CHAT mode)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated context building to use existing API**
- **Found during:** Task 1 (intent_router_node implementation)
- **Issue:** Plan referenced build_context_packet() but actual function is build_context() with ContextSpec
- **Fix:** Used ContextSpec.for_extraction() and build_context() from existing context module
- **Files modified:** src/graph/intent_router.py
- **Verification:** Import and function call work correctly
- **Committed in:** 179692f (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (blocking - API mismatch)
**Impact on plan:** Necessary fix to use existing codebase patterns. No scope creep.

## Issues Encountered

None - plan executed with minor API adaptation.

## Next Phase Readiness

- Unified intent router ready for LangGraph integration
- Phase 39 plan 07 can integrate router into graph.py
- All prior stages (01-05) are now orchestrated through single entry point
- Backward compatibility ensured via to_legacy_intent_result()

---
*Phase: 39-intent-classification-v2*
*Completed: 2026-01-25*
