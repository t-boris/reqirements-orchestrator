---
phase: 41-decision-change-propagation
plan: 03
subsystem: slack-ui
tags: [slack, decision, confirmation, impact-preview, buttons]

# Dependency graph
requires:
  - phase: 41-01
    provides: DecisionChangeOp schema and store
  - phase: 41-02
    provides: ImpactAnalysisService
provides:
  - Impact preview card UI blocks (build_impact_preview_card)
  - Confirmation buttons (Apply updates, Apply to Slack only, Cancel)
  - Button handlers for confirmation flow (decision_change_handlers.py)
  - Integration with existing decision button handlers
affects: [41-04, decision-sync]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Impact preview card with button actions
    - Confirmation flow before Jira writes

key-files:
  created:
    - src/slack/handlers/decision_change_handlers.py
  modified:
    - src/slack/blocks/decision_cards.py
    - src/slack/handlers/decision_buttons.py
    - src/slack/router.py
    - src/slack/handlers/__init__.py

key-decisions:
  - "Impact preview card shows operation type, version, and affected tickets"
  - "Three buttons: Apply updates (Jira), Apply to Slack only (skip Jira), Cancel"
  - "DEPRECATE operation always shows confirmation (has_jira_writes=True)"
  - "EDIT shows confirmation only if has_jira_writes, else auto-confirms"

patterns-established:
  - "Decision change confirmation flow with impact preview"
  - "Skip-Jira option for manual Jira management"

issues-created: []

# Metrics
duration: 15min
completed: 2026-01-26
---

# Phase 41 Plan 03: Confirmation UI - Impact Preview Card Summary

**Impact preview card with confirmation buttons for decision changes - Jira writes always require user confirmation**

## Performance

- **Duration:** 15 min
- **Started:** 2026-01-26T10:00:00Z
- **Completed:** 2026-01-26T10:15:00Z
- **Tasks:** 4
- **Files modified:** 5

## Accomplishments

- Created build_impact_preview_card function showing operation details and affected tickets
- Implemented three confirmation button handlers (apply, slack-only, cancel)
- Integrated confirmation flow into existing change and deprecate modal handlers
- Registered new handlers in router for Slack app

## Task Commits

Each task was committed atomically:

1. **Task 1: Impact preview card builder** - `2567397` (feat)
2. **Task 2: Confirmation button handlers** - `4c2745f` (feat)
3. **Task 3: Integration with decision buttons** - `6527a85` (feat)
4. **Task 4: Handler registration** - `50778ef` (feat)

## Files Created/Modified

- `src/slack/blocks/decision_cards.py` - Added build_impact_preview_card function
- `src/slack/handlers/decision_change_handlers.py` - NEW: Confirmation button handlers
- `src/slack/handlers/decision_buttons.py` - Modified change/deprecate modal submit handlers
- `src/slack/router.py` - Registered new handlers
- `src/slack/handlers/__init__.py` - Exported registration function

## Decisions Made

- **Impact preview shows counts by status:** safe_count, pending_count, conflict_count displayed
- **Conflict details limited to 5:** Shows first 5 conflicting tickets with message
- **High risk warning:** Context block warns user for high impact operations
- **Auto-confirm for no Jira impact:** When has_jira_writes=False, skips confirmation UI
- **Slack-only option:** Allows user to manually manage Jira changes

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Confirmation UI is complete and functional
- Plan 41-04 (Transactional Apply) can now implement DecisionChangeExecutor
- Button handlers are ready to trigger executor when confirmed

---
*Phase: 41-decision-change-propagation*
*Completed: 2026-01-26*
