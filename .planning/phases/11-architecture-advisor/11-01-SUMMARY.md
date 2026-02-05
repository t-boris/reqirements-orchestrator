---
phase: 11-architecture-advisor
plan: 01
subsystem: intent, modes
tags: [architecture, llm, structured-output, pydantic, slack-mrkdwn]

# Dependency graph
requires:
  - phase: 03-intent-and-modes
    provides: SuperMode enum, intent classification, ModeHandler base class
  - phase: 08-smart-ux-layer
    provides: FollowUpQuestion/FollowUpOption models, build_question_blocks
  - phase: 09-decision-lifecycle
    provides: confirm_record_decision action handler
provides:
  - ARCHITECT SuperMode enum value
  - ArchitectModeHandler with architecture-specialized LLM prompts
  - Intent routing for architecture questions
  - Conditional ADR recommendation button
affects: [11-02, future-phases]

# Tech tracking
tech-stack:
  added: []
  patterns: ["specialized-system-prompt-per-mode", "conditional-adr-button"]

key-files:
  created: [src/modes/architect.py]
  modified: [src/intent/schemas.py, src/intent/prompts.py, src/modes/dispatcher.py, src/modes/converse.py]

key-decisions:
  - "Reuse FollowUpQuestion/FollowUpOption from converse.py instead of duplicating"
  - "Single LLM call pattern (like CONVERSE, not multi-phase like JIRA)"
  - "ADR button reuses existing confirm_record_decision action handler with pre-filled value"

patterns-established:
  - "Specialized system prompts per mode: architecture expert with pattern vocabulary and analysis framework"
  - "Conditional action buttons: recommend_adr flag controls ADR button visibility"

issues-created: []

# Metrics
duration: 3min
completed: 2026-02-05
---

# Phase 11 Plan 01: ARCHITECT SuperMode Summary

**New ARCHITECT SuperMode with architecture-expert LLM prompt, structured output (patterns_referenced, tradeoffs, recommend_adr), and conditional ADR recording button**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-05T16:15:17Z
- **Completed:** 2026-02-05T16:18:26Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- Added ARCHITECT as 6th SuperMode with intent classification routing
- Created ArchitectModeHandler with deep architecture-expert system prompt (analysis framework, pattern vocabulary, response structure guidelines)
- Structured output includes patterns_referenced, tradeoffs, and conditional recommend_adr flag
- "Record as ADR" button appears only when LLM makes concrete recommendations, reusing existing confirm_record_decision handler
- CONVERSE prompt updated with architecture mode fallback note

## Task Commits

Each task was committed atomically:

1. **Task 1: Add ARCHITECT to SuperMode enum and intent classification** - `95b6307` (feat)
2. **Task 2: Create ArchitectModeHandler with architecture-specialized prompts** - `fe116bc` (feat)
3. **Task 3: Register in dispatcher and update CONVERSE fallback** - `b9edbcf` (feat)

## Files Created/Modified
- `src/modes/architect.py` - New ARCHITECT mode handler with architecture-expert system prompt and ArchitectResponse schema
- `src/intent/schemas.py` - Added ARCHITECT to SuperMode enum (now 6 modes)
- `src/intent/prompts.py` - Added ARCHITECT mode description and routing rule 11
- `src/modes/dispatcher.py` - Registered ArchitectModeHandler in _handlers dict
- `src/modes/converse.py` - Added architecture mode fallback note to system prompt

## Decisions Made
- Reused FollowUpQuestion/FollowUpOption from converse.py (import, not duplicate) to avoid model drift
- Used single LLM call pattern (same as CONVERSE) since no external API calls needed
- ADR button reuses existing confirm_record_decision action handler with value format matching record.py

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- ARCHITECT mode fully wired: enum, intent routing, handler, dispatcher registration
- Ready for 11-02-PLAN.md (if it exists)
- All 20 existing tests pass with no regressions

---
*Phase: 11-architecture-advisor*
*Completed: 2026-02-05*
