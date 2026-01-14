---
phase: 04-slack-router
plan: 08
subsystem: slack
tags: [dedup, zep, semantic-search, slack-actions]

# Dependency graph
requires:
  - phase: 04
    plan: 03
    provides: SessionIdentity from src/slack/session.py
  - phase: 04
    plan: 05
    provides: search_similar_threads from src/memory/zep_client.py
provides:
  - Dedup suggestion detection with high-confidence threshold (0.85)
  - Non-blocking suggestion UI with action buttons
  - Merge context action handler
  - Ignore suggestion action handler
affects: [04-slack-router, 05-agent-core]

# Tech tracking
tech-stack:
  added: []
  patterns: [semantic-similarity, non-blocking-suggestions, traffic-cop-rule]

key-files:
  created:
    - src/slack/dedup_suggest.py
  modified:
    - src/slack/handlers.py
    - src/slack/router.py

key-decisions:
  - "0.85 similarity threshold to avoid false positives"
  - "Non-blocking suggestion pattern - context note included"
  - "Delete suggestion message on Ignore click"
  - "Link slack:// deep links for thread navigation"

patterns-established:
  - "Rule 2: Traffic Cop - suggest, don't block"
  - "High-confidence only for dedup detection"
  - "Logging similarity score and rationale for debugging"

issues-created: []

# Metrics
duration: 4 min
completed: 2026-01-14
---

# Phase 4 Plan 8: Deduplication Suggestions Summary

**Non-blocking dedup detection with high-confidence threshold and action buttons**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-14
- **Completed:** 2026-01-14
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created dedup suggestion module with 0.85 similarity threshold
- Implemented check_for_duplicates() using Zep semantic search
- Built non-blocking suggestion UI with action buttons
- Added handle_merge_context() handler for "Merge context" button
- Added handle_ignore_dedup() handler for "Ignore" button
- Registered action handlers in router: merge_thread_context, ignore_dedup_suggestion

## Task Commits

Tasks completed:

1. **Task 1: Create dedup suggestion logic** - src/slack/dedup_suggest.py (feat)
2. **Task 2: Add action handlers** - src/slack/handlers.py, src/slack/router.py (feat)

## Files Created/Modified

- `src/slack/dedup_suggest.py` - Dedup detection with SIMILARITY_THRESHOLD=0.85
  - check_for_duplicates() - searches Zep for similar threads
  - build_dedup_suggestion_blocks() - builds Slack Block Kit UI
  - maybe_suggest_dedup() - checks and posts suggestion if found
- `src/slack/handlers.py` - Added handle_merge_context() and handle_ignore_dedup()
- `src/slack/router.py` - Registered merge_thread_context and ignore_dedup_suggestion actions

## Decisions Made

- **0.85 threshold:** High bar to avoid false positives - only extremely similar threads trigger suggestions
- **Non-blocking:** Suggestion includes context note "continue your discussion normally"
- **Delete on ignore:** Message is deleted when user clicks Ignore to reduce noise
- **Slack deep links:** Uses slack:// protocol for cross-thread navigation

## DoD Compliance

Per Definition of Done from 04-CONTEXT.md for Rule 2 (Dedup):
- [x] Non-blocking suggestion only
- [x] Logs similarity score + rationale (in logger.info with extra dict)
- [x] Button: "Merge context" (with action handler)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Verification Results

```
$ python -c "from src.slack.dedup_suggest import maybe_suggest_dedup, check_for_duplicates, SIMILARITY_THRESHOLD; print(f'dedup suggest ok - threshold: {SIMILARITY_THRESHOLD}')"
dedup suggest ok - threshold: 0.85

$ python -c "from src.slack.handlers import handle_merge_context, handle_ignore_dedup; print('action handlers ok')"
action handlers ok

$ python -c "from src.slack.router import register_handlers; print('router ok')"
router ok
```

## Next Phase Readiness

- Dedup suggestions can be triggered from message handlers
- Merge context handler ready to link sessions (TODO: actual session linking)
- Foundation ready for Phase 5 agent integration

---
*Phase: 04-slack-router*
*Completed: 2026-01-14*
