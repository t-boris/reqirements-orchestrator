---
phase: 10-code-review-polish
plan: 01
subsystem: slack-handlers
tags: [slack, action-handlers, json, block-kit, refactoring]

# Dependency graph
requires:
  - phase: 09-decision-lifecycle
    provides: RECORD mode amendment detection, deprecation UI, decision handlers
provides:
  - JSON-based data flow through action.value for RECORD mode buttons
  - Fixed action_ids for deprecation flow (no entity UUID in action_id)
  - Eliminated brittle mrkdwn block parsers
affects: [10-05-adr-lifecycle-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "action.value carries structured JSON data for button handlers"
    - "Fixed action_id + entity ID in value for all non-entity-action buttons"

key-files:
  created: []
  modified:
    - src/modes/record.py
    - src/slack/handlers/actions.py

key-decisions:
  - "Truncate decision text in value JSON (1200 chars description, 500 chars rationale) to stay within Slack 2000-char button value limit"
  - "Keep ENTITY_ACTION_PATTERN (approve/object/discuss) unchanged — those use entity_id in action_id by design and are handled by a different pattern"

patterns-established:
  - "Button value JSON pattern: serialize handler-needed data into action.value, never parse from block text"

issues-created: []

# Metrics
duration: 3min
completed: 2026-02-04
---

# Phase 10 Plan 01: Action Handler Data Flow Summary

**Eliminated brittle mrkdwn block parsers and entity-ID-in-action_id patterns for RECORD mode and deprecation flows**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-04T15:27:00Z
- **Completed:** 2026-02-04T15:29:49Z
- **Tasks:** 4
- **Files modified:** 2

## Accomplishments
- Decision data (title, type, description, rationale, alternatives) now serialized as JSON in button `value` fields
- Deleted `_parse_record_mode_preview()` (60 lines) and `_parse_amend_preview()` (57 lines) — replaced with `json.loads(action["value"])`
- Deprecation buttons use fixed `action_id` ("deprecate_decision", "confirm_deprecate", "cancel_deprecate") with entity ID in `value`
- Block format changes can no longer silently break the confirm/amend/edit/deprecate data flow

## Task Commits

Each task was committed atomically:

1. **Task 1: Store decision data as JSON in action.value** - `0f05940` (feat)
2. **Task 2: Replace block parsers with JSON deserialization** - `37fb1aa` (refactor)
3. **Task 3: Fix deprecation buttons - fixed action_id** - `c0355ee` (refactor)
4. **Task 4: Run tests** - no commit (verification only, 20 passed, 9 skipped)

## Files Created/Modified
- `src/modes/record.py` - Added JSON value serialization to all RECORD mode preview buttons (Record, Edit, Amend, Record as New)
- `src/slack/handlers/actions.py` - Deleted 2 brittle parsers, updated handlers to read from action.value, fixed deprecation action_ids

## Decisions Made
- Truncate description to 1200 chars and rationale to 500 chars in value JSON to stay within Slack's 2000-char button value limit
- Keep ENTITY_ACTION_PATTERN (approve/object/discuss) unchanged — it uses entity_id in action_id by design and is the standard Slack pattern for entity-specific actions

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- ISS-003 (brittle parsers) and ISS-004 (entity IDs in action_id) are resolved
- Ready for 10-02-PLAN.md (dashboard UX improvements)

---
*Phase: 10-code-review-polish*
*Completed: 2026-02-04*
