---
phase: 22-multi-ticket-from-review
plan: 01
subsystem: graph
tags: [llm, extraction, multi-ticket, jira]

# Dependency graph
requires:
  - phase: 20-brain-refactor
    provides: MultiTicketState, WorkflowStep, PendingAction types
provides:
  - extract_multi_items_from_review() async function
  - MULTI_ITEM_EXTRACTION_PROMPT constant
  - Multi-item detection in scope gate handler
affects: [22-02, 22-03, 22-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "UUID-based item tracking for parent linking before Jira keys exist"
    - "parent_index to parent_id resolution for hierarchy"

key-files:
  created: []
  modified:
    - src/graph/nodes/extraction.py
    - src/slack/handlers/review.py

key-decisions:
  - "Use parent_index in LLM response, convert to parent_id with UUIDs after parsing"
  - "Route 2+ items to multi-ticket preview, single item to existing flow"

patterns-established:
  - "Multi-item extraction from review text with hierarchy detection"

issues-created: []

# Metrics
duration: 8min
completed: 2026-01-16
---

# Phase 22 Plan 01: Multi-Item Extraction Summary

**LLM-based extraction of multiple work items from review text with hierarchy detection for epic/story relationships**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-16T21:17:00Z
- **Completed:** 2026-01-16T21:25:29Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- Added `extract_multi_items_from_review()` async function for LLM-based item extraction
- Added `MULTI_ITEM_EXTRACTION_PROMPT` that handles both "N epics" and "1 epic with N stories" cases
- Modified scope gate handler to detect multi-items and route to appropriate flow
- Added `_show_multi_ticket_preview()` helper for state management and UI posting

## Task Commits

Each task was committed atomically:

1. **Task 1-2: Multi-item extraction function and prompt** - `7df6eb7` (feat)
2. **Task 3: Scope gate handler multi-item routing** - `c9e4e37` (feat)

## Files Created/Modified

- `src/graph/nodes/extraction.py` - Added MULTI_ITEM_EXTRACTION_PROMPT and extract_multi_items_from_review() function
- `src/slack/handlers/review.py` - Modified scope gate handler, added _show_multi_ticket_preview() helper

## Decisions Made

1. **parent_index to parent_id conversion** - LLM returns array indices for parent references, which are converted to UUIDs after parsing. This avoids asking LLM to generate UUIDs.
2. **Single-item fallback** - If extraction returns 1 item, use existing single-ticket flow for richer draft editing experience.
3. **Zero-item handling** - Post helpful error message asking user to describe what to create.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Multi-item extraction function ready for use
- Scope gate properly routes to multi-ticket preview
- Ready for 22-02: Multi-ticket handler registration and UI interactions

---
*Phase: 22-multi-ticket-from-review*
*Completed: 2026-01-16*
