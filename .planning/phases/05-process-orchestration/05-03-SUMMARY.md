---
phase: 05-process-orchestration
plan: 03
subsystem: orchestration
tags: [flow-templates, dataclass, task-orchestration]

# Dependency graph
requires:
  - phase: 05-01
    provides: Task and Workspace models for orchestration
provides:
  - FlowTemplate dataclass for defining task execution patterns
  - 6 predefined flows (create_work_item, create_decision, architecture_review, batch_create, review, converse)
  - Helper functions (get_flow_template, can_complete, missing_context, suggested_next)
affects: [05-04, 05-05, 05-06, 05-07]

# Tech tracking
tech-stack:
  added: []
  patterns: [frozen-dataclass, flow-as-guide, registry-pattern]

key-files:
  created:
    - src/orchestration/flows.py
  modified:
    - src/orchestration/__init__.py

key-decisions:
  - "Flows are guides not enforcers - suggest context but don't require order"
  - "Frozen dataclass for immutability and hashability"
  - "CONVERSE as default fallback for unknown flow types"

patterns-established:
  - "FlowTemplate: frozen dataclass with suggested/required context"
  - "Registry pattern: FLOW_TEMPLATES dict for lookup by flow_type"
  - "Helper functions operate on context dict + flow template"

issues-created: []

# Metrics
duration: 3min
completed: 2026-02-02
---

# Plan 05-03: FlowTemplate Definitions Summary

**Frozen FlowTemplate dataclass with 6 predefined flows (create_work_item, create_decision, architecture_review, batch_create, review, converse) and helper functions for context management**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-02T19:05:00Z
- **Completed:** 2026-02-02T19:08:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created FlowTemplate frozen dataclass that guides (not enforces) task execution
- Defined 6 flow templates covering common task patterns
- Implemented helper functions for context evaluation (can_complete, missing_context, suggested_next)
- Exported all flows and helpers from orchestration package root

## Task Commits

Each task was committed atomically:

1. **Task 1: Create FlowTemplate dataclass and predefined flows** - `98e2b5b` (feat)
2. **Task 2: Update orchestration __init__.py with flow exports** - `df2ab13` (feat)

## Files Created/Modified
- `src/orchestration/flows.py` - FlowTemplate dataclass, 6 predefined flows, helper functions
- `src/orchestration/__init__.py` - Export FlowTemplate and all flows from package root

## Decisions Made
- Flows guide but don't enforce: suggested_context is a hint, only required_context must be present
- Frozen dataclass ensures FlowTemplate is immutable and hashable
- CONVERSE flow as fallback for unknown types (get_flow_template returns it for any unknown flow_type)

## Deviations from Plan

None - plan executed exactly as written

## Issues Encountered

None

## Next Phase Readiness
- FlowTemplate ready for use in Orchestrator (05-04, 05-05)
- Helper functions available for task context management
- All 6 flow templates match 05-MODEL-PROPOSAL.md design

---
*Plan: 05-03*
*Completed: 2026-02-02*
