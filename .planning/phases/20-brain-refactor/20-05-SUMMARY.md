---
phase: 20-brain-refactor
plan: 05
subsystem: routing
tags: [event-routing, slack, idempotency, workflow]

# Dependency graph
requires:
  - phase: 20-01
    provides: UserIntent, PendingAction, WorkflowStep, WorkflowEventType enums
  - phase: 20-02
    provides: EventStore for idempotency tracking
  - phase: 20-03
    provides: validate_event, validate_ui_version, stale UI messages
provides:
  - Event-first routing with route_event function
  - RouteResult enum for routing outcomes
  - RoutingDecision dataclass for structured routing
  - is_workflow_event detection for buttons/commands/modals
  - extract_event_info for parsing Slack events
affects: [20-06-handler-integration, slack-handlers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Event-first routing: WorkflowEvent -> PendingAction -> ThreadDefault -> Intent
    - Idempotency via event_id tracking
    - Dataclass for routing decisions

key-files:
  created:
    - src/slack/event_router.py
    - tests/test_event_router.py
  modified: []

key-decisions:
  - "RouteResult as Enum for typed routing outcomes"
  - "RoutingDecision dataclass for structured decisions with optional fields"
  - "UI version parsed from button value suffix (format: value:version)"
  - "Thread default expires check uses ISO timestamp comparison"

patterns-established:
  - "Event routing priority: idempotency -> workflow_event -> pending_action -> thread_default -> intent"

issues-created: []

# Metrics
duration: 2min
completed: 2026-01-16
---

# Phase 20 Plan 05: Event Router Summary

**Event-first routing module that prioritizes workflow events over intent classification, with idempotency protection and stale UI detection**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-16T00:54:14Z
- **Completed:** 2026-01-16T00:56:07Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created event router module with route_event function implementing 5-step priority routing
- RouteResult enum for 5 routing outcomes: WORKFLOW_EVENT, CONTINUATION, INTENT_CLASSIFY, DUPLICATE, STALE_UI
- is_workflow_event detects button clicks, slash commands, and modal submissions
- extract_event_info parses Slack events for event type, action, and UI version
- 24 unit tests covering all routing scenarios

## Task Commits

Each task was committed atomically:

1. **Task 1: Create event router module** - `79f0455` (feat)
2. **Task 2: Add unit tests for event router** - `46cd240` (test)

## Files Created/Modified
- `src/slack/event_router.py` - Event-first routing with route_event function
- `tests/test_event_router.py` - 24 unit tests for routing logic

## Decisions Made
- RouteResult as string Enum (inherits from str, Enum) for JSON serialization
- RoutingDecision as dataclass with Optional fields for different outcomes
- UI version parsed from button value using rsplit(":", 1) - supports format "value:version"
- Thread default expiry check handles timezone-aware ISO timestamps

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Event router ready for handler integration (20-06)
- All verification criteria met:
  - Module imports successfully
  - Priority order implemented correctly
  - 24/24 tests pass
  - Full test suite (168 tests) passes

---
*Phase: 20-brain-refactor*
*Completed: 2026-01-16*
