# Plan 20-12: Intent Router Simplification - Summary

**Plan:** 20-12-PLAN.md
**Status:** COMPLETED
**Execution Time:** ~10 minutes
**Commits:** 4

## What Was Done

### Task 1: Simplify IntentType in intent.py
**Commit:** 2ada094

Simplified IntentType enum from 7 values to 5 pure user intents:
- **Removed:** TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION
- **Added:** META (questions about bot capabilities)
- **Kept:** TICKET, REVIEW, DISCUSSION, AMBIGUOUS

Key changes:
- Removed TICKET bias in LLM prompts - now defaults to AMBIGUOUS
- Removed has_review_context parameter (handled before intent classification)
- Removed unused pattern constants (TICKET_ACTION_PATTERNS, etc.)
- Updated module docstring to explain the separation

### Task 2: Update graph.py route_after_intent
**Commit:** 538a502

Added scope_gate_node and updated routing for new intents:
- Created `src/graph/nodes/scope_gate.py` for AMBIGUOUS intent handling
- Added scope_gate_flow routing in route_after_intent
- META routes to discussion_flow (same response style)
- AMBIGUOUS routes to scope_gate_flow (3-button choice)
- Added thread_default_intent override for AMBIGUOUS

Graph routes:
- TICKET -> ticket_flow (extraction)
- REVIEW -> review_flow
- DISCUSSION -> discussion_flow
- META -> discussion_flow
- AMBIGUOUS -> scope_gate_flow

### Task 3: Integrate event router in handlers/core.py
**Commit:** 83666b2

Updated _process_mention to use event-first routing:
- Added event router integration before intent classification
- Added _handle_continuation for pending action routing
- Event router checks: DUPLICATE -> STALE_UI -> CONTINUATION -> INTENT_CLASSIFY

### Task 4: Skip deprecated tests
**Commit:** 4466334

Skipped tests for patterns now handled by event_router:
- TestTicketActionPatterns (3 classes)
- TestReviewContinuationPatterns (all classes in file)
- TestDecisionApprovalStillWorks

Result: 120 passed, 56 skipped

## Architecture Impact

The "brain split" from 20-CONTEXT.md is now partially implemented:
- **UserIntent** (what user wants): TICKET, REVIEW, DISCUSSION, META, AMBIGUOUS
- **PendingAction** (what system is doing): Handled by event_router before graph

Routing priority order:
1. WorkflowEvent (button/slash) - event_router
2. PendingAction - event_router continuation
3. Thread default intent - overrides AMBIGUOUS
4. Classified intent - route to flow

## Files Changed

| File | Change |
|------|--------|
| src/graph/intent.py | Simplified IntentType, removed patterns |
| src/graph/graph.py | Added scope_gate routing |
| src/graph/nodes/scope_gate.py | NEW - scope gate node |
| src/slack/handlers/core.py | Event router integration |
| tests/test_intent_continuation.py | Skipped (deprecated) |
| tests/test_intent_router.py | Skipped TICKET_ACTION tests |

## Verification

- All imports verified
- Syntax validated via ast.parse
- 120 tests passed, 56 skipped (deprecated behavior)
- No circular import issues

## Decisions Made

1. **AMBIGUOUS default instead of TICKET**: Reduces aggressive ticket creation, lets user decide via scope gate
2. **META -> discussion_flow**: Bot capability questions get brief responses like greetings
3. **Backward compatibility routes**: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION routes kept for migration but these are now PendingActions

## Next Steps

Phase 20-13 (if exists) should:
- Wire up scope gate button handlers to re-route through graph
- Complete pending action continuation handling
- Update event_router tests for new patterns
