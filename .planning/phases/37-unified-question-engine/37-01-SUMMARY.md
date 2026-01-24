---
phase: 37-unified-question-engine
plan: "01"
subsystem: questions
tags: [protocol, pydantic, review-state, question-provider]

# Dependency graph
requires:
  - phase: 36-question-engine-conversation-driver
    provides: QuestionTask schema, QuestionCatalog, AnswerMapper
provides:
  - QuestionProvider Protocol interface
  - ProviderType enum (CATALOG, FREEFORM)
  - ReviewState schema with nested models
affects: [37-02 CatalogProvider, 37-03 FreeformProvider, review-continuation]

# Tech tracking
tech-stack:
  added: []
  patterns: [Protocol pattern for provider interface]

key-files:
  created:
    - src/questions/provider.py
    - src/schemas/review_state.py
  modified:
    - src/questions/__init__.py
    - src/schemas/__init__.py

key-decisions:
  - "Protocol pattern for QuestionProvider (not ABC)"
  - "ReviewState mirrors WorkItemDraft as FreeformProvider target"
  - "OpenQuestion tracks maps_to field for answer routing"

patterns-established:
  - "Provider Protocol with generate_question() and get_target_type()"
  - "ReviewState nested models: Assumption, Constraint, Risk, OpenQuestion, ProposedDecision"

issues-created: []

# Metrics
duration: 5min
completed: 2026-01-24
---

# Phase 37 Plan 01: QuestionProvider Interface + ReviewState Schema Summary

**Foundation for unified Question Engine with abstract provider interface and ReviewState target schema**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-24T13:43:00Z
- **Completed:** 2026-01-24T13:48:09Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created QuestionProvider Protocol defining the interface for question providers
- Added ProviderType enum with CATALOG (WorkItemDraft) and FREEFORM (ReviewState) values
- Created ReviewState schema as target for FreeformProvider with full nested model hierarchy

## Task Commits

Each task was committed atomically:

1. **Task 1: Create QuestionProvider interface** - `f40c7fe` (feat)
2. **Task 2: Create ReviewState schema** - `adb9b95` (feat)

## Files Created/Modified
- `src/questions/provider.py` - QuestionProvider Protocol and ProviderType enum
- `src/schemas/review_state.py` - ReviewState and nested models (Assumption, Constraint, Risk, OpenQuestion, ProposedDecision)
- `src/questions/__init__.py` - Export QuestionProvider and ProviderType
- `src/schemas/__init__.py` - Export ReviewState and all nested models

## Decisions Made
- Used Protocol pattern (not ABC) for QuestionProvider interface - enables structural subtyping
- ReviewState mirrors the role of WorkItemDraft - serves as target state for FreeformProvider
- OpenQuestion includes `maps_to` field to route answers to specific ReviewState fields

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- QuestionProvider interface ready for CatalogProvider extraction (37-02)
- ReviewState schema ready for FreeformProvider implementation (37-03)
- All types exported from packages for downstream use

---
*Phase: 37-unified-question-engine*
*Completed: 2026-01-24*
