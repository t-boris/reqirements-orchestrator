---
phase: 25-workitem-centric
plan: 02
subsystem: intent
tags: [ops, debug, explain, intent, classification, langgraph]

# Dependency graph
requires:
  - phase: 25-01
    provides: Documentation updates for workitem-centric architecture
provides:
  - OPS intent with DEBUG and EXPLAIN subtypes
  - OpsSubtype enum in schemas
  - ops_node LangGraph node
  - /maro explain slash command
  - OPS response dispatcher
affects: [intent-classification, graph-routing, slash-commands, response-dispatch]

# Tech tracking
tech-stack:
  added: []
  patterns: [intent-subtype, forced-intent-injection]

key-files:
  created:
    - src/schemas/intent.py
    - src/graph/nodes/ops.py
  modified:
    - src/graph/intent.py
    - src/graph/graph.py
    - src/slack/handlers/commands.py
    - src/slack/handlers/dispatch.py
    - src/slack/onboarding.py

key-decisions:
  - "OPS intent uses subtypes (DEBUG, EXPLAIN) rather than separate intents"
  - "WORKITEM_CREATE replaces TICKET with dual-stack backward compatibility"
  - "Auto-normalize TICKET to WORKITEM_CREATE during parsing"

patterns-established:
  - "Intent subtype pattern: Single intent enum with ops_subtype field"
  - "Forced intent injection: Commands can inject intent_result to bypass classification"

issues-created: []

# Metrics
duration: 25min
completed: 2026-01-22
---

# Phase 25.2: Intent Rename + OPS Intent Summary

**OPS intent with DEBUG/EXPLAIN subtypes for error triage and decision explanation, plus TICKET to WORKITEM_CREATE rename with backward compatibility**

## Performance

- **Duration:** 25 min
- **Started:** 2026-01-22
- **Completed:** 2026-01-22
- **Tasks:** 8
- **Files modified:** 7

## Accomplishments
- Created OPS intent with DEBUG (error triage) and EXPLAIN (policy trace) subtypes
- Renamed TICKET to WORKITEM_CREATE with dual-stack backward compatibility
- Added /maro explain command to force OPS:EXPLAIN flow
- Built ops_node LangGraph node with system operator style prompts
- Integrated OPS flow into graph router and response dispatcher

## Task Commits

Each task was committed atomically:

1. **Task 1: Update Intent enum with OPS and WORKITEM_CREATE** - `a41d297` (feat)
2. **Task 2-3: Update intent classification prompt and parsing** - `b4bd5cd` (feat)
3. **Task 4: Create OPS flow node** - `30e57bc` (feat)
4. **Task 5: Add OPS flow to graph router** - `f850558` (feat)
5. **Task 6: Add /maro explain command** - `b6f7c2e` (feat)
6. **Task 7: Update help text with new commands** - `28865e0` (docs)
7. **Task 8: Add OPS response dispatcher** - `a934aa3` (feat)

## Files Created/Modified

Created:
- `src/schemas/intent.py` - Centralized Intent enum with OpsSubtype, IntentResult
- `src/graph/nodes/ops.py` - OPS flow node with DEBUG/EXPLAIN prompts

Modified:
- `src/graph/intent.py` - Updated classification prompt with OPS, WORKITEM_CREATE
- `src/graph/graph.py` - Added ops_flow routing and ops node
- `src/slack/handlers/commands.py` - Added /maro explain command
- `src/slack/handlers/dispatch.py` - Added _handle_ops_response dispatcher
- `src/slack/onboarding.py` - Updated help text with Operations section

## Decisions Made
- OPS intent uses subtypes rather than separate DEBUG/EXPLAIN intents for shared infrastructure
- TICKET remains as deprecated alias, auto-normalized to WORKITEM_CREATE
- ops_node uses system operator style prompts (not LLM introspection)
- /maro explain creates a thread if not in one

## Deviations from Plan

None - plan executed exactly as written

## Issues Encountered

None

## Next Phase Readiness
- OPS intent and flow complete, ready for Phase 25.3 (CHANGE_REQUEST)
- Intent classification now includes OPS triggers for error patterns and explanation requests
- Dual-stack TICKET/WORKITEM_CREATE migration ready for production testing

---
*Phase: 25-workitem-centric*
*Plan: 02*
*Completed: 2026-01-22*
