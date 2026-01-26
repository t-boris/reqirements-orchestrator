---
phase: 40-decision-v2-rich-context
plan: 01
subsystem: decisions
tags: [pydantic, schema, decisions, rich-context]

# Dependency graph
requires:
  - phase: 30-decision-first-class-entity
    provides: Decision and DecisionVersion base schemas
provides:
  - RationaleItem, Alternative, Consequence rich context models
  - Decision schema with rationale, context, alternatives, consequences fields
  - DecisionVersion schema with rich context for history
  - Helper methods: has_rich_context(), rationale_summary(), to_rich_context_dict()
affects: [40-02 (database), 40-03 (extraction), 40-04 (UI), 40-05 (projection)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Rich context models for structured reasoning capture
    - Optional fields for backward compatibility
    - list[dict] in DecisionVersion for JSON serialization

key-files:
  created: []
  modified:
    - src/schemas/decision.py

key-decisions:
  - "Structured models (not plain text) for rationale, alternatives, consequences"
  - "RationaleItem has optional weight (primary/secondary) for importance"
  - "Consequence has optional severity (minor/moderate/major)"
  - "DecisionVersion uses list[dict] instead of models for JSON serialization"

patterns-established:
  - "Rich context fields are all Optional for backward compatibility"
  - "Helper methods on model for common operations"

issues-created: []

# Metrics
duration: 8min
completed: 2026-01-25
---

# Phase 40 Plan 01: Rich Context Field Models Summary

**Extended Decision schema with RationaleItem, Alternative, Consequence models and helper methods for WHY reasoning capture**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-25T23:40:00Z
- **Completed:** 2026-01-25T23:48:00Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments

- Added RationaleItem, Alternative, Consequence Pydantic models for structured rich context
- Extended Decision schema with rationale, context, alternatives, consequences fields
- Extended DecisionVersion schema with matching fields for version history
- Added helper methods: has_rich_context(), rationale_summary(), to_rich_context_dict()

## Task Commits

Each task was committed atomically:

1. **Task 1: Add rich context field models** - `0ec47c9` (feat)
2. **Task 2: Add rich fields to Decision and DecisionVersion** - `475d934` (feat)
3. **Task 3: Add helper methods for rich context** - `7a263f3` (feat)

## Files Created/Modified

- `src/schemas/decision.py` - Extended with rich context models and fields

## Decisions Made

- Structured models (RationaleItem, Alternative, Consequence) instead of plain text for:
  - UI rendering with appropriate formatting
  - LLM extraction with validation
  - Jira projection with proper formatting
- RationaleItem has optional `weight` field (primary/secondary) to indicate importance
- Consequence has optional `severity` field (minor/moderate/major) for impact tracking
- DecisionVersion uses `list[dict]` instead of typed models for JSON serialization compatibility
- All rich context fields are Optional for backward compatibility with existing decisions

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Rich context models ready for database persistence (40-02)
- Decision schema ready for LLM extraction (40-03)
- Helper methods ready for UI rendering (40-04)
- to_rich_context_dict() ready for Jira projection (40-05)

---
*Phase: 40-decision-v2-rich-context*
*Completed: 2026-01-25*
