---
phase: 37-unified-question-engine
plan: "05"
subsystem: questions
tags: [question-engine, freeform-provider, review-continuation, unified-interface]

# Dependency graph
requires:
  - phase: 37-02
    provides: CatalogProvider for WorkItemDraft questions
  - phase: 37-03
    provides: FreeformProvider for ReviewState questions
  - phase: 37-04
    provides: AnswerMapper for processing responses
provides:
  - QuestionEngine unified facade for all question flows
  - FreeformProvider integration in review_continuation
  - Package-level QuestionEngine export
affects: [review-flow, ticket-collection, conversation-handlers]

# Tech tracking
tech-stack:
  added: []
  patterns: [unified-facade-pattern, intent-detection-before-llm]

key-files:
  created: [src/questions/engine.py]
  modified: [src/graph/nodes/review_continuation.py, src/questions/__init__.py]

key-decisions:
  - "QuestionEngine wraps both providers with unified interface"
  - "Intent detection (_wants_questions_asked) happens BEFORE LLM call for determinism"
  - "FreeformProvider generates structured questions for review flow"

patterns-established:
  - "Unified facade pattern: QuestionEngine wraps CatalogProvider + FreeformProvider"
  - "Early intent check: detect user intent before expensive LLM call"

issues-created: []

# Metrics
duration: 7min
completed: 2026-01-24
---

# Phase 37 Plan 05: QuestionEngine + Review Integration Summary

**Unified QuestionEngine facade with FreeformProvider integration in review_continuation for consistent question UX across ticket and review paths**

## Performance

- **Duration:** 7 min
- **Started:** 2026-01-24T13:50:00Z
- **Completed:** 2026-01-24T13:57:12Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Created QuestionEngine as unified facade wrapping CatalogProvider and FreeformProvider
- Integrated FreeformProvider in review_continuation for "ask me questions" flow
- Added intent detection to check for question requests BEFORE LLM call
- Exported QuestionEngine from src.questions package

## Task Commits

Each task was committed atomically:

1. **Task 1: Create unified QuestionEngine** - `1153918` (feat)
2. **Task 2: Update review_continuation to use Question Engine** - `b2b2911` (feat)
3. **Task 3: Export QuestionEngine** - `434dd46` (feat)

## Files Created/Modified

- `src/questions/engine.py` - QuestionEngine unified facade with should_ask, generate_question, process_button_answer, process_text_answer
- `src/graph/nodes/review_continuation.py` - Added _wants_questions_asked and _generate_review_questions helpers, early intent check
- `src/questions/__init__.py` - Added QuestionEngine export

## Decisions Made

- QuestionEngine wraps both providers rather than inheriting - maintains flexibility
- Intent detection happens BEFORE LLM call - saves LLM cost and ensures deterministic behavior
- FreeformProvider generates 3 questions by default, rotating through missing fields

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Phase 37 COMPLETE - all 5 plans executed
- QuestionEngine provides unified interface for ticket and review question flows
- Both paths now use same UX patterns (QuestionTask format, budget tracking)

---
*Phase: 37-unified-question-engine*
*Completed: 2026-01-24*
