---
phase: 04-slack-router
plan: 09
subsystem: slack
tags: [contradiction, constraints, cross-thread, slack-ui]

# Dependency graph
requires:
  - plan: 04-06
    provides: KnowledgeStore with find_conflicting_constraints()
  - plan: 04-03
    provides: SessionIdentity for thread context
provides:
  - Contradiction detection for accepted constraints
  - Slack alert UI with resolution buttons
  - get_constraints_summary() for epic queries
affects: [05-agent-core]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Structured constraint conflict detection (subject match + value differs)
    - Action button values encoding data as pipe-delimited strings
    - Async handlers with fast-ack pattern

key-files:
  created:
    - src/slack/contradiction.py
  modified:
    - src/slack/handlers.py
    - src/slack/router.py

key-decisions:
  - "Only check accepted constraints (not proposed) to reduce noise"
  - "Three resolution options: mark conflict, override previous, keep both"
  - "Action data encoded in button value for stateless handler"

patterns-established:
  - "check_for_contradictions() queries KG for same subject, different value, accepted status"
  - "build_contradiction_alert_blocks() creates Slack Block Kit UI with action buttons"
  - "Resolution handlers parse pipe-delimited data from action value"

issues-created: []

# Metrics
duration: 4min
completed: 2026-01-14
---

# Phase 04 Plan 09: Contradiction Detector Summary

**Contradiction detection system for structured constraints with Slack alert UI and resolution actions.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-14
- **Completed:** 2026-01-14
- **Tasks:** 2 (+ router update)
- **Files modified:** 3

## Accomplishments

- Created contradiction.py with detection and alert functions
- Implemented three resolution action handlers (conflict, override, keep both)
- Registered all action handlers in router
- Added get_constraints_summary() to answer "What constraints exist for this epic?"

## Verification

All verification commands passed:
```
python -c "from src.slack.contradiction import maybe_alert_contradiction" -> OK
python -c "from src.slack.handlers import handle_contradiction_conflict, handle_contradiction_override" -> OK
python -c "from src.slack.router import register_handlers" -> OK
```

## Files Created/Modified

### Created
- `src/slack/contradiction.py` - Contradiction detection and alert building
  - `check_for_contradictions()` - Finds conflicts on same subject with different value
  - `build_contradiction_alert_blocks()` - Builds Slack Block Kit UI with resolution buttons
  - `maybe_alert_contradiction()` - Checks and posts alert if found
  - `get_constraints_summary()` - Answers "What constraints exist for this epic?"

### Modified
- `src/slack/handlers.py` - Added three contradiction resolution handlers:
  - `handle_contradiction_conflict()` - Marks values as conflicting
  - `handle_contradiction_override()` - New value supersedes old
  - `handle_contradiction_both()` - Keep both as intentional
- `src/slack/router.py` - Registered action handlers:
  - `resolve_contradiction_conflict`
  - `resolve_contradiction_override`
  - `resolve_contradiction_both`

## Design Decisions

1. **Only accepted constraints**: Proposed constraints are not checked - reduces noise from tentative decisions
2. **Structured matching**: Subject must match exactly, value must differ - no fuzzy matching
3. **User confirmation required**: All resolutions require user to click a button
4. **Stateless handlers**: All data encoded in action value (pipe-delimited string)

## Alert UI Structure

The contradiction alert contains:
1. Header: "Potential Contradiction Detected"
2. New constraint: subject = value
3. Existing conflicts: list with thread links
4. Resolution prompt
5. Action buttons: Mark as conflict (danger), Override previous (primary), Keep both
6. Context note explaining detection criteria

## Deviations from Plan

None - plan executed exactly as written.

## TODOs Left for Future Plans

The resolution handlers have placeholder TODOs for actual KG updates:
- Update constraint status to 'conflicted' in KG
- Mark old constraint as 'deprecated'
- Mark new constraint as 'accepted'
- Update Epic summary with conflicts/resolutions

These will be implemented when the full agent flow connects in Phase 5.

## DoD Checklist

- [x] Only checks accepted constraints (not proposed)
- [x] Subject match + value differs = conflict triggers alert
- [x] Resolution buttons: conflict/override/both
- [x] get_constraints_summary answers "What constraints exist?"
- [x] User confirmation required for resolution

---
*Phase: 04-slack-router*
*Completed: 2026-01-14*
