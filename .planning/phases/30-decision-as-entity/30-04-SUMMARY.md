---
phase: 30-decision-as-entity
plan: 04
subsystem: slack
tags: [decision, canonical-message, thread-binding, slack-api]

# Dependency graph
requires:
  - phase: 30-01
    provides: Decision entity and DecisionStore with versioning
provides:
  - DecisionManager service for canonical message pattern
  - Thread binding for decision discussions
  - get_by_canonical_message() for finding decisions from threads
affects: [decision-ui, decision-approval, decision-discussion]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Canonical message pattern - one message per decision, updated in place"
    - "Thread binding - route thread messages to associated decision"

key-files:
  created:
    - src/slack/decision_manager.py
  modified:
    - src/db/decision_store.py

key-decisions:
  - "post_canonical_message() stores ts in database for future updates"
  - "update_canonical_message() uses chat_update (not new message) for update-in-place"
  - "Thread binding queries by channel_id + canonical_message_ts"

patterns-established:
  - "Canonical message: channel = live state board, not archive"
  - "Update in place: same message moves in time"

issues-created: []

# Metrics
duration: 5min
completed: 2026-01-24
---

# Phase 30 Plan 04: DecisionManager Canonical Message Pattern Summary

**DecisionManager service with post_canonical_message, update_canonical_message, post_to_discussion_thread, and thread binding**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-24T01:02:00Z
- **Completed:** 2026-01-24T01:07:48Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- Created DecisionManager service for canonical message management
- Implemented update-in-place pattern (chat_update, not new messages)
- Added thread binding to route discussion thread messages to correct decision
- Added get_by_canonical_message() to DecisionStore for thread lookup

## Task Commits

Each task was committed atomically:

1. **Task 1: Create DecisionManager service** - `d3d2ca0` (feat)
2. **Task 2+3: Add thread binding and get_by_canonical_message** - `bb87080` (feat)

## Files Created/Modified

- `src/slack/decision_manager.py` - DecisionManager with canonical message pattern
- `src/db/decision_store.py` - Added get_by_canonical_message() method

## Decisions Made

- Thread binding via canonical_message_ts lookup (when user posts in decision thread, we find the decision by querying canonical_message_ts)
- mark_deprecated() imports build_deprecated_decision_blocks from decision_cards (to be created in future plan)
- pin_canonical_message() catches exceptions to handle "already pinned" gracefully

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- DecisionManager ready for integration with decision approval flow
- Thread binding enables routing discussion thread messages to decision refinement
- Canonical message pattern implements CONTEXT.md vision: "channel = live state board"

---
*Phase: 30-decision-as-entity*
*Completed: 2026-01-24*
