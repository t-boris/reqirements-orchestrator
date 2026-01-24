---
phase: 30-decision-as-entity
plan: 03
subsystem: intent
tags: [decision, intent-routing, pattern-matching, langgraph]

# Dependency graph
requires:
  - phase: 30-01
    provides: Decision entity and DecisionStore
provides:
  - DECISION intent type in Intent enum
  - Decision detection patterns and type hints
  - decision_extraction_node for creating Decision from user message
affects: [30-06, 30-07, 30-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Pattern-first intent detection before LLM
    - Type hinting via keyword matching

key-files:
  created:
    - src/graph/nodes/decision_extraction.py
  modified:
    - src/schemas/intent.py
    - src/graph/intent.py

key-decisions:
  - "Pattern matching runs before LLM with 0.9 confidence for decision detection"
  - "8 decision patterns cover common decision statement forms"
  - "6 decision type keywords map to DecisionType enum values"
  - "Title extraction removes 'We decided to...' prefixes for cleaner display"

patterns-established:
  - "Pattern-first routing: Check regex patterns before LLM classification"
  - "Type hinting: Use keywords to suggest decision type without LLM"

issues-created: []

# Metrics
duration: 5min
completed: 2026-01-24
---

# Phase 30 Plan 03: DECISION Intent and Detection Summary

**DECISION intent type added with pattern-first detection and decision extraction node for creating Decision entities from user statements.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-24T01:06:04Z
- **Completed:** 2026-01-24T01:10:49Z
- **Tasks:** 3/3
- **Files modified:** 3

## Accomplishments

- Added DECISION intent to Intent enum with decision_type_hint and decision_title_hint fields
- Implemented 8 regex patterns for detecting decision statements ("We decided to...", "Approved:", etc.)
- Created 6 keyword categories for decision type hinting (arch, scope, constraint, priority, structure, process)
- Built decision_extraction_node that creates Decision in PROPOSED status

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DECISION intent type** - `a8dc2a5` (feat)
2. **Task 2: Add decision detection patterns** - `3913712` (feat)
3. **Task 3: Create decision extraction node** - `be05255` (feat)

## Files Created/Modified

- `src/schemas/intent.py` - Added DECISION intent and decision hint fields
- `src/graph/intent.py` - Added pattern matching and LLM prompt updates
- `src/graph/nodes/decision_extraction.py` - New node for decision creation

## Decisions Made

1. **Pattern-first detection with 0.9 confidence** - Decision patterns are checked before LLM classification for faster routing
2. **8 decision patterns** - Cover common forms: "We decided", "The decision is", "Approved:", "Let's go with", "Agreed:", "Confirmed:", "Final call:", "architecture will use"
3. **6 decision type keywords** - Map to DecisionType: arch (15 keywords), scope (10), constraint (8), priority (10), structure (8), process (6)
4. **Title cleanup** - Removes "We decided to..." prefixes for cleaner decision titles

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- DECISION intent detection complete
- decision_extraction_node creates Decision in PROPOSED status
- Ready for graph routing integration (30-06) and handler updates (30-07)

---
*Phase: 30-decision-as-entity*
*Completed: 2026-01-24*
