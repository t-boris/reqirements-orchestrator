---
phase: 12-onboarding-ux
plan: 02
subsystem: slack
tags: [llm, onboarding, hints, buttons, persona]

# Dependency graph
requires:
  - phase: 03-llm-integration
    provides: get_llm() unified chat client
  - phase: 09-personas
    provides: handle_persona_command for switching
provides:
  - classify_hesitation() LLM-based intent detection
  - HintType enum and HintResult model
  - Contextual hint system with buttons
  - hint_select_* action handlers
affects: [12-03-help-command, future-onboarding]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - LLM-based intent classification for hesitation detection
    - Contextual hints with optional action buttons
    - Pattern-based action routing (hint_select_*)

key-files:
  created:
    - src/slack/onboarding.py
  modified:
    - src/graph/nodes/extraction.py
    - src/slack/handlers.py
    - src/slack/blocks.py
    - src/slack/router.py

key-decisions:
  - "Pattern match greetings/perspective questions for speed"
  - "Fall back to LLM for nuanced classification"
  - "Buttons use hint_select_{value} pattern for routing"

patterns-established:
  - "Contextual hints: one sentence, not lectures"
  - "Button actions follow hint_select_* pattern"

issues-created: []

# Metrics
duration: 15min
completed: 2026-01-15
---

# Phase 12 Plan 02: Hesitation Detection Summary

**LLM-based hesitation detection with contextual hints and persona selection buttons**

## Performance

- **Duration:** 15 min
- **Started:** 2026-01-15T10:00:00Z
- **Completed:** 2026-01-15T10:15:00Z
- **Tasks:** 4/4
- **Files modified:** 5

## Accomplishments

- Created onboarding module with LLM-based hesitation classification
- Replaced static intro/nudge messages with contextual hints
- Added button support for persona selection from hints
- Registered hint button action handlers in router

## Task Commits

Each task was committed atomically:

1. **Task 1: Create onboarding module** - `97b410e` (feat)
2. **Task 2: Update extraction node** - `a51a2aa` (feat)
3. **Task 3: Add hint dispatch handling** - `c7a8231` (feat)
4. **Task 4: Add hint button handlers** - `b418412` (feat)

## Files Created/Modified

- `src/slack/onboarding.py` - New module with HintType, HintResult, classify_hesitation()
- `src/graph/nodes/extraction.py` - Uses classify_hesitation for empty draft handling
- `src/slack/handlers.py` - handle_hint_selection() and hint action dispatch
- `src/slack/blocks.py` - build_hint_with_buttons() for button-based hints
- `src/slack/router.py` - Register hint_select_* action pattern

## Decisions Made

1. **Pattern match obvious cases first** - Greetings and perspective questions use simple patterns for speed
2. **LLM for nuanced classification** - VAGUE_IDEA and CONFUSED use LLM to understand intent
3. **Buttons use value-based routing** - hint_select_{value} pattern allows flexible expansion

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Hesitation detection ready for production
- 12-03 (Interactive /maro help) can build on hint patterns
- All persona buttons work from hint context

---
*Phase: 12-onboarding-ux*
*Completed: 2026-01-15*
