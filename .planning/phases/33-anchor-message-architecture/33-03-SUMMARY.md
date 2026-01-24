---
phase: 33-anchor-message-architecture
plan: 03
subsystem: database
tags: [workitem, anchor, pydantic, slack-blocks, psycopg]

# Dependency graph
requires:
  - phase: 33-01
    provides: AnchorMessage schema, AnchorStore with bidirectional lookups
provides:
  - WorkItem canonical message fields (canonical_message_ts, canonical_channel_id)
  - WorkItemStore anchor tracking methods (set_canonical_message, get_by_canonical_message)
  - WorkItem anchor block builder (build_workitem_anchor_blocks)
affects: [33-04, 33-05]  # Context resolution, anchor posting integration

# Tech tracking
tech-stack:
  added: []
  patterns: [workitem-anchor-pattern, type-status-emoji-mapping]

key-files:
  created:
    - src/slack/blocks/workitem.py
  modified:
    - src/db/models.py
    - src/db/workitem_store.py

key-decisions:
  - "Optional fields (canonical_message_ts, canonical_channel_id) because legacy WorkItems don't have anchors"
  - "Type emojis: purple=epic, blue=story, white=task, red=bug, orange=spike"
  - "Status-based action buttons: draft gets Edit/Approve/Discard, active gets Update/Done/Jira"

patterns-established:
  - "WorkItem anchor message format: {type_emoji} *{key}* - {title} with status line below"
  - "AnchorStore integration from WorkItemStore for reverse lookup"

issues-created: []

# Metrics
duration: 12min
completed: 2026-01-24
---

# Phase 33 Plan 03: WorkItem Canonical Message Tracking Summary

**WorkItem schema extended with anchor fields, store with tracking methods, and block builder for anchor messages**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-24T03:55:00Z
- **Completed:** 2026-01-24T04:07:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added canonical_message_ts and canonical_channel_id fields to WorkItem model
- Created set_canonical_message() and get_by_canonical_message() methods in WorkItemStore
- Built comprehensive WorkItem anchor block builder with type/status emojis and action buttons

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Canonical Message Fields to WorkItem** - `3b9ab46` (feat)
2. **Task 2: Add WorkItemStore Methods for Anchor Tracking** - `06774ea` (feat)
3. **Task 3: Create WorkItem Anchor Block Builder** - `6bdcebe` (feat)

**Plan metadata:** (will be committed with this summary)

## Files Created/Modified

- `src/db/models.py` - Added canonical_message_ts and canonical_channel_id fields to WorkItem
- `src/db/workitem_store.py` - Added migration for new columns, set_canonical_message, get_by_canonical_message methods
- `src/slack/blocks/workitem.py` - New file with build_workitem_anchor_blocks and helper functions

## Decisions Made

1. **Optional anchor fields** - canonical_message_ts and canonical_channel_id are Optional because legacy WorkItems created before Phase 33 don't have anchors yet
2. **Type emoji mapping** - Visual distinction: purple=epic, blue=story, white=task, red=bug, orange=spike
3. **Status-based buttons** - DRAFT gets Edit/Approve/Discard, ACTIVE gets Update/Done/Jira, DONE gets Reopen

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tasks completed successfully.

## Next Phase Readiness

- WorkItem schema ready for anchor message posting
- Block builder ready for integration with Slack message posting
- AnchorStore integration enables reverse lookup (message -> WorkItem)
- Ready for 33-04 (Context Resolution) and 33-05 (Anchor Posting Integration)

---
*Phase: 33-anchor-message-architecture*
*Completed: 2026-01-24*
