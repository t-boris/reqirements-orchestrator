---
phase: 30-decision-as-entity
plan: 02
subsystem: database
tags: [pydantic, postgres, decision-link, jira-projection]

# Dependency graph
requires:
  - phase: 30-01
    provides: Decision, DecisionType, DecisionStatus schemas
provides:
  - DecisionLink schema for decision-to-Jira mappings
  - JiraFieldPath enum for deterministic field targeting
  - DecisionLinkStore with CRUD and sync tracking
  - DECISION_MAPPING_RULES for DecisionType -> JiraFieldPath
affects: [30-03, 30-04, 30-05, 30-06]

# Tech tracking
tech-stack:
  added: []
  patterns: [sync-tracking-pattern, deterministic-mapping]

key-files:
  created:
    - src/db/decision_link_store.py
  modified:
    - src/schemas/decision.py

key-decisions:
  - "JiraFieldPath enum with 7 standardized field targets (including CUSTOM_FIELD extension point)"
  - "DECISION_MAPPING_RULES provides deterministic DecisionType -> JiraFieldPath mapping"
  - "Sync tracking via synced_version and synced_at enables incremental updates"

patterns-established:
  - "Deterministic mapping: Decision type -> Jira field (no LLM guessing)"
  - "Sync tracking pattern: version-based sync state per link"

issues-created: []

# Metrics
duration: 3min
completed: 2026-01-24
---

# Phase 30 Plan 02: DecisionLink Table Summary

**DecisionLink schema with JiraFieldPath enum and DecisionLinkStore for deterministic decision-to-Jira projection**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-24T00:59:49Z
- **Completed:** 2026-01-24T01:02:47Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- JiraFieldPath enum with 7 standardized field targets for decision projection
- DecisionLink schema with sync tracking (synced_version, synced_at)
- DecisionLinkStore with full CRUD: link, unlink, query by decision/ticket, sync tracking
- DECISION_MAPPING_RULES dict mapping all 6 DecisionTypes to JiraFieldPaths
- get_default_field_path() helper for deterministic mapping lookups

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DecisionLink schema** - `48e6fec` (feat)
2. **Task 2: Create DecisionLinkStore** - `d7da924` (feat)
3. **Task 3: Add mapping rules helper** - `1f09e78` (feat)

## Files Created/Modified

- `src/schemas/decision.py` - Added JiraFieldPath enum, DecisionLink model, DECISION_MAPPING_RULES, get_default_field_path()
- `src/db/decision_link_store.py` - New store for decision-to-Jira mappings with sync tracking

## Decisions Made

- **JiraFieldPath has 7 values** - 6 for decision types + CUSTOM_FIELD extension point
- **Sync tracking is per-link** - Each decision-ticket pair tracks its own sync version
- **Deterministic mapping** - No LLM involved in deciding where decisions appear in Jira

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- DecisionLink foundation complete, ready for decision store integration (plan 03)
- Deterministic mapping rules enable predictable Jira projection behavior

---
*Phase: 30-decision-as-entity*
*Completed: 2026-01-24*
