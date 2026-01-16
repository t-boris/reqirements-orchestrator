---
phase: 20-brain-refactor
plan: 08
subsystem: review
tags: [patch-mode, llm, slack-blocks, architecture-review]

# Dependency graph
requires:
  - phase: 20-04
    provides: pending_payload contract for version tracking
  - phase: 20-05
    provides: UI version parsing from button values
  - phase: 20-06
    provides: Scope gate patterns
provides:
  - Patch mode prompt for efficient review continuations
  - Full synthesis function for complete architecture view
  - Slack blocks for patch/full review UIs
affects: [review-handlers, decision-approval]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Patch mode for incremental updates (4 sections, max 12 bullets)
    - Version tracking in review_context

key-files:
  created:
    - src/slack/blocks/review.py
  modified:
    - src/graph/nodes/review_continuation.py
    - src/graph/nodes/review.py
    - src/slack/blocks/__init__.py

key-decisions:
  - "Patch mode as default - reduces expensive full regeneration"
  - "4-section structure: New Decisions, New Risks, New Open Questions, Changes Since"
  - "Full synthesis triggered by explicit button click"

patterns-established:
  - "is_patch and is_full_synthesis flags in decision_result for UI detection"
  - "Version tracking in review_context for patch iterations"

issues-created: []

# Metrics
duration: 4min
completed: 2026-01-16
---

# Phase 20 Plan 08: Patch Mode for Reviews Summary

**Patch mode for review continuations with 4-section structure, reducing expensive full regeneration on every user answer**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-16T01:04:12Z
- **Completed:** 2026-01-16T01:07:57Z
- **Tasks:** 3/3
- **Files modified:** 4

## Accomplishments

- Patch mode prompt outputs only changes (4 sections, max 12 bullets)
- Full synthesis function combines all patches into complete document
- Slack blocks with "Show Full Architecture" and "Approve & Post Decision" buttons
- Version tracking enables patch iteration history

## Task Commits

Each task was committed atomically:

1. **Task 1: Create patch generation prompt** - `156cf7c` (feat)
2. **Task 2: Add full synthesis function** - `3d90064` (feat)
3. **Task 3: Add "Show full architecture" button** - `dc71325` (feat)

## Files Created/Modified

- `src/graph/nodes/review_continuation.py` - Added PATCH_REVIEW_PROMPT, updated node to use patch mode by default
- `src/graph/nodes/review.py` - Added FULL_SYNTHESIS_PROMPT and generate_full_synthesis() function
- `src/slack/blocks/review.py` - New file with build_patch_review_blocks() and build_full_synthesis_blocks()
- `src/slack/blocks/__init__.py` - Export new review block builders

## Decisions Made

- **Patch mode as default**: Reduces expensive LLM calls by outputting only changes instead of full regeneration
- **Fixed 4-section structure**: New Decisions, New Risks, New Open Questions, Changes Since vN (max 12 bullets total)
- **Explicit full synthesis**: Only triggered by "Show Full Architecture" button click, not automatic

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Patch mode and full synthesis ready for handler integration
- Handlers need to detect `is_patch` and `is_full_synthesis` flags to use appropriate block builders
- Button handlers (`review_show_full`, `review_approve_decision`) need implementation in handlers

---
*Phase: 20-brain-refactor*
*Completed: 2026-01-16*
