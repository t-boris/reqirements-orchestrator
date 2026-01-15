---
phase: 14-architecture-decisions
plan: 01
subsystem: graph
tags: [intent-routing, slack-blocks, architecture-decisions]

# Dependency graph
requires:
  - phase: 13-intent-router
    provides: Intent classification framework, IntentType enum
provides:
  - DECISION_APPROVAL intent type
  - review_context field in AgentState
  - build_decision_blocks() for channel posts
  - decision_approval_node for graph routing
affects: [handlers, reviews, channel-posts]

# Tech tracking
tech-stack:
  added: []
  patterns: ["approval-detection-after-review", "channel-post-not-thread"]

key-files:
  created:
    - src/graph/nodes/decision_approval.py
  modified:
    - src/graph/intent.py
    - src/schemas/state.py
    - src/graph/nodes/review.py
    - src/slack/blocks.py
    - src/slack/handlers.py
    - src/graph/graph.py

key-decisions:
  - "DECISION_APPROVAL patterns only checked when has_review_context=True"
  - "review_context stored after review_node, cleared after decision posted"
  - "Decision posted to channel (not thread) as permanent record"

patterns-established:
  - "Thread = thinking process, Channel = approved decisions"

issues-created: []

# Metrics
duration: 15min
completed: 2026-01-15
---

# Phase 14 Plan 01: Architecture Decision Records Summary

**Auto-detect and record architecture decisions when user approves a review**

## Performance

- **Duration:** 15 min
- **Started:** 2026-01-15T12:50:00Z
- **Completed:** 2026-01-15T13:05:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- DECISION_APPROVAL intent type with 9 detection patterns (let's go with this, approved, ship it, etc.)
- review_context field added to AgentState for tracking recent reviews
- review_node now saves review context after successful analysis
- decision_approval_node packages context for handler processing
- build_decision_blocks() formats decisions with topic, decision, and thread link
- Handler extracts decision via LLM and posts formatted message to channel

## Task Commits

Each task was committed atomically:

1. **Task 1: Decision approval detection and review context storage** - `84f989d` (feat)
2. **Task 2: Decision extraction and channel posting** - `49f3b8f` (feat)

## Files Created/Modified

- `src/graph/intent.py` - Added DECISION_APPROVAL IntentType and patterns
- `src/schemas/state.py` - Added review_context field to AgentState
- `src/graph/nodes/review.py` - Save review_context after analysis
- `src/graph/nodes/decision_approval.py` - New node for approval flow
- `src/slack/blocks.py` - Added build_decision_blocks() function
- `src/slack/handlers.py` - Added DECISION_EXTRACTION_PROMPT and decision_approval action
- `src/graph/graph.py` - Added decision_approval node and routing

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| DECISION_APPROVAL patterns only checked when has_review_context=True | Prevents false positives - "sounds good" in other contexts shouldn't trigger |
| review_context stored after review_node, cleared after decision posted | State lifecycle: review -> approval -> clear |
| Decision posted to channel (not thread) | Follows vision: Thread = thinking, Channel = decisions |

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Phase 14 complete - Architecture Decision Records implemented
- User can now get reviews and approve them with "let's go with this" style phrases
- Approved decisions posted to channel as permanent record with thread link

---
*Phase: 14-architecture-decisions*
*Completed: 2026-01-15*
