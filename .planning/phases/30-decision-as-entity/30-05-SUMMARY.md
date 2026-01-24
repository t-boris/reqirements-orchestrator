---
phase: 30-decision-as-entity
plan: 05
subsystem: ui
tags: [slack-blocks, decision-cards, decision-ui, visual-states]

# Dependency graph
requires:
  - phase: 30-01
    provides: Decision entity schema with DecisionType, DecisionStatus
provides:
  - Decision UI blocks for all four visual states
  - Version-bound button payloads for state binding
  - Type emojis for all 6 DecisionTypes
affects: [30-06, 30-07, 30-08]

# Tech tracking
tech-stack:
  added: []
  patterns: [four-visual-states-pattern, version-bound-payloads]

key-files:
  created: [src/slack/blocks/decision_cards.py]
  modified: []

key-decisions:
  - "Four visual states match psychological weight: draft (compact) -> approval (heavy) -> approved (authoritative) -> commit log (ultra compact)"
  - "Version-bound button payloads contain decision_id + version to prevent stale clicks"
  - "Type emojis visually distinguish decision types (ARCH=brain, SCOPE=ruler, CONSTRAINT=lock, etc.)"

patterns-established:
  - "Four visual states: idea -> proposal -> law -> record"
  - "Version-bound JSON payloads in action buttons"

issues-created: []

# Metrics
duration: 2min
completed: 2026-01-24
---

# Phase 30 Plan 05: Decision UI Blocks Summary

**Decision card blocks with four visual states matching psychological weight: compact draft for discussion, full block for approval moment, compact authoritative for approved, ultra compact for commit log**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-24T01:06:03Z
- **Completed:** 2026-01-24T01:08:20Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments

- Created `build_compact_draft_card()` for PROPOSED decisions (lightweight, tentative)
- Created `build_approval_block()` for approval moment (heavy, formal with dividers)
- Created `build_approved_card()` for APPROVED decisions (compact but authoritative)
- Created `build_commit_log_entry()` for Channel Work Board (ultra compact, pure signal)
- Created `build_deprecated_decision_blocks()` for deprecated decisions with replacement pointers
- All buttons have version-bound JSON payloads (decision_id + version)
- Type emojis for all 6 DecisionTypes

## Task Commits

Each task was committed atomically:

1. **Task 1: Create compact draft card** - `05f559a` (feat)
2. **Task 2: Create full approval block** - `ef4b753` (feat)
3. **Task 3: Create approved card and commit log entry** - `ddf1a80` (feat)

## Files Created/Modified

- `src/slack/blocks/decision_cards.py` - Decision card blocks for all four visual states

## Decisions Made

- Four visual states match psychological weight from CONTEXT.md
- Type emojis: ARCH=brain, SCOPE=ruler, CONSTRAINT=lock, PRIORITY=lightning, STRUCTURE=construction, PROCESS=gear
- Version-bound button payloads prevent stale clicks (same pattern as Phase 27.4)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Decision UI blocks ready for integration with handlers
- All four visual states implemented as specified in CONTEXT.md
- Ready for 30-06 (Decision detection/creation flow)

---
*Phase: 30-decision-as-entity*
*Completed: 2026-01-24*
