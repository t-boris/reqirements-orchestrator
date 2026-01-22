---
phase: 25-workitem-centric
plan: 03
subsystem: graph, slack
tags: [intent, change-request, diff, pydantic]

# Dependency graph
requires:
  - phase: 25-02
    provides: Intent enum in src/schemas/intent.py
provides:
  - CHANGE_REQUEST intent classification
  - ChangeRequest/ChangePreview schemas
  - change_request_flow graph node
  - Diff preview UI with approval buttons
affects: [25-05, jira-sync]

# Tech tracking
tech-stack:
  added: []
  patterns: [diff-preview-approval]

key-files:
  created:
    - src/schemas/change_request.py
    - src/graph/nodes/change_request.py
    - src/slack/blocks/change_request.py
    - src/slack/handlers/change_request.py
  modified:
    - src/schemas/intent.py
    - src/graph/intent.py
    - src/graph/graph.py
    - src/slack/handlers/dispatch.py
    - src/slack/handlers/__init__.py
    - src/slack/router.py

key-decisions:
  - "CHANGE_REQUEST intent for structural changes (split, merge, delete, move) vs JIRA_COMMAND for single field updates"
  - "Diff preview with Approve/Edit/Cancel buttons before applying changes"
  - "Handlers use sync wrapper pattern (_run_async) like other button handlers"

patterns-established:
  - "Diff preview pattern: node -> preview blocks -> handler on approval"
  - "change_targets/change_operation fields in IntentResult for extraction"

issues-created: []

# Metrics
duration: 15min
completed: 2026-01-22
---

# Phase 25.3: CHANGE_REQUEST Intent Summary

**Diff-based update flow with CHANGE_REQUEST intent routing, preview UI, and approval buttons**

## Performance

- **Duration:** 15 min
- **Started:** 2026-01-22T18:00:00Z
- **Completed:** 2026-01-22T18:15:00Z
- **Tasks:** 8
- **Files modified:** 10

## Accomplishments

- CHANGE_REQUEST intent classification with LLM detection for structural changes
- ChangeRequest/ChangePreview pydantic schemas for diff tracking
- change_request_flow node in graph for handling intent
- Slack blocks for diff preview UI with Approve/Edit/Cancel buttons
- Full dispatch and button handler registration

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ChangeRequest schemas** - `1fd78e7` (feat)
2. **Task 2: Update intent classification for CHANGE_REQUEST** - `ecdfc5f` (feat)
3. **Task 3: Create change_request flow node** - `ab99184` (feat)
4. **Task 4: Create change request Slack blocks** - `3ab38fc` (feat)
5. **Task 5: Create change request handlers** - `604bb12` (feat)
6. **Task 6: Add change_request_flow to graph** - `c477a08` (feat)
7. **Task 7: Add dispatch handler for change_request_preview** - `d6e1db6` (feat)
8. **Task 8: Register button handlers** - `8b64bad` (feat)

## Files Created/Modified

- `src/schemas/change_request.py` - ChangeRequest, ChangePreview, FieldChange schemas
- `src/schemas/intent.py` - Added change_targets, change_operation fields to IntentResult
- `src/graph/intent.py` - CHANGE_REQUEST detection in LLM classification prompt
- `src/graph/nodes/change_request.py` - change_request_node flow handler
- `src/graph/graph.py` - Added change_request_flow routing
- `src/slack/blocks/change_request.py` - Preview and applied confirmation blocks
- `src/slack/handlers/change_request.py` - Button action handlers
- `src/slack/handlers/dispatch.py` - change_request_preview dispatch
- `src/slack/handlers/__init__.py` - Handler exports
- `src/slack/router.py` - Button handler registration

## Decisions Made

- CHANGE_REQUEST for structural changes (split, merge, delete, move, rename)
- JIRA_COMMAND remains for single field updates (priority, status)
- Handlers registered in router.py following existing pattern
- AgentState accessed via .get() for safe key access

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Handler signature pattern**
- **Found during:** Task 5 (Create handlers)
- **Issue:** Plan showed async handlers with direct params, but Slack needs sync wrappers with ack/body/client
- **Fix:** Rewrote handlers to use sync wrapper pattern (_run_async) matching other handlers
- **Files modified:** src/slack/handlers/change_request.py
- **Verification:** Pattern matches handle_update_preview_apply in update.py
- **Committed in:** 8b64bad (Task 8 commit)

**2. [Rule 3 - Blocking] AgentState import**
- **Found during:** Task 3 (change_request node)
- **Issue:** Plan imported from src/graph/state but actual location is src/schemas/state
- **Fix:** Changed import to src/schemas/state
- **Files modified:** src/graph/nodes/change_request.py
- **Verification:** Import succeeds
- **Committed in:** ab99184 (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (2 blocking), 0 deferred
**Impact on plan:** Necessary corrections for Slack handler pattern and correct imports. No scope creep.

## Issues Encountered

None

## Next Phase Readiness

- CHANGE_REQUEST flow functional (preview, approve, cancel, edit)
- Ready for 25-05 which depends on 25-02, 25-03, 25-04
- LLM extraction of changes is placeholder - will need enhancement for complex diffs

---
*Phase: 25-workitem-centric*
*Plan: 03*
*Completed: 2026-01-22*
