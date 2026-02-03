---
phase: 08-smart-ux-layer
plan: 01
subsystem: ui
tags: [slack, block-kit, pydantic, buttons, structured-output]

# Dependency graph
requires:
  - phase: 03-intent-and-modes
    provides: ConverseLLMResponse and ModeResult with response_blocks
  - phase: 02-slack-integration
    provides: Slack Bolt action handlers and block builders
provides:
  - Structured follow-up questions in LLM responses (FollowUpOption, FollowUpQuestion models)
  - Slack button rendering for choice/confirmation questions
  - Button click handler with post-selection message update
  - "Something else" freeform escape hatch
affects: [08-smart-ux-layer]

# Tech tracking
tech-stack:
  added: []
  patterns: [structured-llm-questions, button-based-ux, post-selection-update]

key-files:
  created: [src/slack/blocks/questions.py]
  modified: [src/modes/converse.py, src/slack/handlers/actions.py, src/slack/blocks/__init__.py]

key-decisions:
  - "Preserve non-action blocks when updating message after button click"
  - "Sort questions by priority (higher first) before rendering"
  - "Always reserve 1 button slot for Something else escape hatch (max 4 options + 1)"

patterns-established:
  - "Question button action_id format: answer_q_{uuid8}_{index}"
  - "Button value payload: JSON with question_text, answer, thread_ts (max 255 chars)"

issues-created: []

# Metrics
duration: 3min
completed: 2026-02-03
---

# Phase 8 Plan 01: LLM Question Extraction + Button Rendering Summary

**Structured follow-up questions with Slack button rendering for choice/confirmation, freeform escape hatch, and post-selection message updates**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-03T05:39:24Z
- **Completed:** 2026-02-03T05:42:18Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Extended ConverseLLMResponse with FollowUpQuestion/FollowUpOption Pydantic models for structured LLM output
- Created build_question_blocks() rendering choice/confirmation questions as Slack buttons with "Something else" escape hatch
- Added answer_q_* button click handler that updates original message with Q/A summary and posts answer as thread message
- Updated CONVERSE_SYSTEM prompt with guidance for when to use choice vs confirmation vs open_ended

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend ConverseLLMResponse with follow-up questions** - `60e36e1` (feat)
2. **Task 2: Add button click handler and post-selection update** - `b4ad0b3` (feat)

## Files Created/Modified
- `src/modes/converse.py` - Added FollowUpOption, FollowUpQuestion models; extended ConverseLLMResponse; updated system prompt; added block building to handle()
- `src/slack/blocks/questions.py` - New module: build_question_blocks() with choice/confirmation/open_ended support
- `src/slack/handlers/actions.py` - Added answer_q handler for button clicks, message update, freeform escape hatch
- `src/slack/blocks/__init__.py` - Exported build_question_blocks

## Decisions Made
- Preserve non-action blocks when updating message after button click (keeps original response text visible)
- Sort questions by priority descending before rendering buttons
- Reserve 1 button slot for "Something else" (max 4 option buttons + 1 escape = 5 total, within Slack limit)
- Truncate question_text in button value payload if needed to stay under 255 char Slack limit

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Follow-up question rendering complete, ready for 08-02 (Intent Audit Logging)
- Event handlers already route response_blocks through say() - no additional wiring needed

---
*Phase: 08-smart-ux-layer*
*Completed: 2026-02-03*
