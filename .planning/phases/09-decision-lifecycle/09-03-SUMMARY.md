---
phase: 09-decision-lifecycle
plan: 03
subsystem: slack-handlers
tags: [slack, record-mode, amendment, action-handlers, adr]

# Dependency graph
requires:
  - phase: 09-decision-lifecycle
    provides: DecisionAmended event, amend_decision() method, projection handler
provides:
  - RECORD mode detects existing decisions in thread and offers amendment
  - confirm_amend_decision Slack action handler with full amendment flow
  - Amendment preview blocks with Amend/Record as New/Cancel buttons
  - Old ADR message marked as amended when decision is updated
affects: [09-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [amendment-detection-before-duplicate, entity-id-in-button-value]

key-files:
  modified:
    - src/modes/record.py
    - src/slack/handlers/actions.py

key-decisions:
  - "Entity ID encoded in button value JSON rather than parsed from blocks -- reliable across block structure changes"
  - "Most recent decision used when multiple exist in thread (last in entity list)"
  - "Non-amendable entities (Approved/Committed) get descriptive error suggesting deprecation workflow"

patterns-established:
  - "Amendment detection: load aggregate, query entities in thread, filter by type, offer amend if found"
  - "Old ADR message updated with warning context block prepended to existing blocks"

issues-created: []

# Metrics
duration: 2min
completed: 2026-02-04
---

# Phase 9 Plan 3: RECORD Mode Amendment Detection + Slack Handlers Summary

**RECORD mode detects existing decisions in thread and offers amendment preview with Amend/Record as New/Cancel; confirm_amend_decision handler completes full amendment flow including old ADR marking and dashboard update**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-04T14:37:13Z
- **Completed:** 2026-02-04T14:39:26Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- RECORD mode now detects existing decisions in thread via get_entities_in_thread and shows amendment preview instead of duplicate recording
- Amendment preview displays current decision content, proposed update, and three buttons: Amend Decision, Record as New, Cancel
- confirm_amend_decision handler parses entity_id from button value, validates amendability, posts new ADR, calls amend_decision, marks old ADR as amended, and updates dashboard
- Non-amendable entities (Approved/Committed) receive helpful error message suggesting deprecation workflow

## Task Commits

Each task was committed atomically:

1. **Task 1: Add existing decision detection to RECORD mode** - `b03e7a3` (feat)
2. **Task 2: Register confirm_amend_decision handler in actions.py** - `db7f489` (feat)

## Files Created/Modified
- `src/modes/record.py` - Added load_aggregate import, EntityType import, existing decision detection in _create_decision_preview, _build_amendment_preview_blocks method with entity_id in button value
- `src/slack/handlers/actions.py` - Updated RECORD_CONFIRM_PATTERN regex, added _parse_amend_preview helper, added confirm_amend_decision handler branch with full flow (validate, amend, post ADR, mark old ADR, update dashboard)

## Decisions Made
- Entity ID is encoded in the Amend button's value field as JSON rather than parsing from block structure -- more reliable and survives block format changes
- When multiple decisions exist in a thread, the most recent one (last in entities list) is used for amendment
- Non-amendable entity states (Approved, Committed) get a descriptive error message suggesting the deprecation + re-record workflow instead of amendment

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Amendment detection and handler are fully wired, ready for 09-04 (Deprecation UI + dashboard enhancement)
- Existing confirm_record_decision and cancel_decision flows remain unchanged
- _parse_amend_preview helper available for reuse if needed
- All 20 existing tests pass

---
*Phase: 09-decision-lifecycle*
*Completed: 2026-02-04*
