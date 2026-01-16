---
phase: 20-brain-refactor
plan: 09
subsystem: graph
tags: [multi-ticket, epic, stories, safety-latch, slack-blocks]

# Dependency graph
requires:
  - phase: 20-07
    provides: ReviewArtifact frozen handoff pattern
  - phase: 20-08
    provides: Patch mode review blocks pattern
provides:
  - MultiTicketState TypedDict for epic + stories batches
  - MultiTicketItem TypedDict for individual items in batch
  - Safety latch thresholds (quantity >3, size >10k)
  - extract_multi_ticket() node for LLM-based extraction
  - Preview blocks with edit capability
affects: [20-10, multi-ticket-handlers, jira-batch-create]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Safety latches: >3 items or >10k chars require explicit confirmation"
    - "MultiTicketItem with parent_id links stories to Epic (not subtasks)"
    - "ui_version in button action_id for stale click detection"

key-files:
  created:
    - src/graph/nodes/multi_ticket.py
    - src/slack/blocks/multi_ticket.py
  modified:
    - src/schemas/state.py
    - src/slack/blocks/__init__.py

key-decisions:
  - "Stories linked to Epic via parent_id (not Jira subtasks)"
  - "Quantity threshold set to 3 (>3 requires confirmation)"
  - "Size threshold set to 10k chars (>10k triggers batch split option)"

patterns-established:
  - "Multi-ticket safety latches before creation"
  - "TypedDict items with parent_id for Epic-Story relationships"

issues-created: []

# Metrics
duration: 4min
completed: 2026-01-16
---

# Phase 20 Plan 09: Multi-Ticket Foundation Summary

**MultiTicketState data model with Epic + linked stories, quantity/size safety latches, and preview blocks**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-16T01:10:13Z
- **Completed:** 2026-01-16T01:13:46Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- MultiTicketState and MultiTicketItem TypedDicts for batch ticket creation
- Safety latch thresholds: MULTI_TICKET_QUANTITY_THRESHOLD (3), MULTI_TICKET_SIZE_THRESHOLD (10000)
- extract_multi_ticket() async node with LLM-based epic + stories extraction
- Preview blocks showing all items with per-item Edit buttons
- Quantity and size confirmation blocks for safety latches

## Task Commits

Each task was committed atomically:

1. **Task 1: Add MultiTicketState to state.py** - `a417827` (feat)
2. **Task 2: Create multi-ticket extraction node** - `6fa1110` (feat)
3. **Task 3: Create multi-ticket preview blocks** - `6d75092` (feat)

## Files Created/Modified

- `src/schemas/state.py` - Added MultiTicketState, MultiTicketItem, safety thresholds, multi_ticket_state field in AgentState
- `src/graph/nodes/multi_ticket.py` - New extraction node with LLM-based JSON parsing and safety latches
- `src/slack/blocks/multi_ticket.py` - New blocks for quantity confirm, size confirm, and full preview
- `src/slack/blocks/__init__.py` - Export new block builders

## Decisions Made

- Stories linked via parent_id to Epic (not Jira subtasks) - follows 20-CONTEXT.md requirement for configurable Epic-Story relationships
- Quantity threshold >3 items (not >=3) - small batches (2-3 items) don't need confirmation
- Size threshold 10000 chars - approximately 5-10 stories worth of content

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Multi-ticket state model ready for handler integration
- Safety latches implemented and tested
- Preview blocks can be used by multi-ticket handlers
- Ready for 20-10: Multi-ticket Jira creation handlers

---
*Phase: 20-brain-refactor*
*Completed: 2026-01-16*
