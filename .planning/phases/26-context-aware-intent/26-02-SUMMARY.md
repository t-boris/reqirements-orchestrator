---
phase: 26-context-aware-intent
plan: 02
subsystem: intent
tags: [intent-classification, llm, draft-context, context-awareness]

requires:
  - phase: 26-01
    provides: IssueType and RequestedScope enums, type fields on TicketDraft

provides:
  - DRAFT_REFINE intent for draft refinement questions
  - context_relation field on IntentResult
  - Context-aware intent classification with draft state

affects: [ticket-flow, extraction, decision]

tech-stack:
  added: []
  patterns:
    - "Context-aware intent classification pattern"
    - "Draft state passed through classification chain"

key-files:
  created: []
  modified:
    - src/schemas/intent.py
    - src/graph/intent.py
    - src/graph/graph.py

key-decisions:
  - "DRAFT_REFINE routes to ticket_flow (not a separate flow)"
  - "context_relation uses four values: continue, refine, change, new_topic"

patterns-established:
  - "Pass draft summary through intent classification chain"
  - "Inject active context into LLM classification prompts"

issues-created: []

duration: 4min
completed: 2026-01-22
---

# Phase 26 Plan 02: Context-Aware Intent Classification Summary

**Added DRAFT_REFINE intent and context-aware classification with active draft state awareness**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-22T20:05:08Z
- **Completed:** 2026-01-22T20:09:25Z
- **Tasks:** 6
- **Files modified:** 3

## Accomplishments

- Added DRAFT_REFINE intent to Intent enum for draft refinement questions
- Added context_relation field to IntentResult for tracking message relationship to context
- Updated LLM classifier to accept and use active draft state
- Added comprehensive DRAFT_REFINE rules to classification prompt
- Intent router now extracts draft summary and passes to classifier
- DRAFT_REFINE routes to ticket_flow for continued draft work

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DRAFT_REFINE intent** - `14fcde4` (feat)
2. **Task 2: Add context_relation field** - `81de938` (feat)
3. **Task 3: Update _llm_classify signature** - `9b64213` (feat)
4. **Task 4: Add DRAFT_REFINE to LLM prompt** - `777d6b0` (feat)
5. **Task 5: Update intent_router_node** - `b8ba72b` (feat)
6. **Task 6: Add draft_refine route to graph** - `0ef1dc3` (feat)

## Files Created/Modified

- `src/schemas/intent.py` - Added DRAFT_REFINE intent and context_relation field
- `src/graph/intent.py` - Updated classification with draft context awareness
- `src/graph/graph.py` - Added DRAFT_REFINE routing to ticket_flow

## Decisions Made

- **DRAFT_REFINE routes to ticket_flow:** Instead of creating a separate flow, DRAFT_REFINE routes back to ticket_flow so the bot can continue asking clarifying questions about draft structure
- **context_relation values:** Four values chosen (continue, refine, change, new_topic) to cover all relationship types between message and active context

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Context-aware intent classification is functional
- Ready for Plan 03: Extract issue_type and scope from user requests
- Ready for Plan 04: Draft continuity rule in decision node

---
*Phase: 26-context-aware-intent*
*Completed: 2026-01-22*
