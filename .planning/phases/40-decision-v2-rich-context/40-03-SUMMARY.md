---
phase: 40-decision-v2-rich-context
plan: 03
subsystem: decisions
tags: [llm, extraction, decisions, rich-context]

# Dependency graph
requires:
  - phase: 40-01
    provides: Rich context field models (RationaleItem, Alternative, Consequence)
  - phase: 40-02
    provides: Database schema with rich context columns
provides:
  - RICH_CONTEXT_EXTRACTION_PROMPT for structured LLM extraction
  - extract_rich_context() async function for conversation analysis
  - _build_conversation_context() helper for message formatting
  - decision_extraction_node with rich context integration
affects: [40-04 (UI), 40-05 (projection)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - LLM extraction with low temperature (0.3) for structured output
    - Graceful degradation on extraction failures
    - Context size limits (3000 chars) for token control

key-files:
  created: []
  modified:
    - src/graph/nodes/decision_extraction.py

key-decisions:
  - "Low temperature (0.3) for consistent JSON output from LLM"
  - "Best-effort extraction - errors logged but don't block decision creation"
  - "Conversation context limited to 3000 chars to control token usage"
  - "Max 10 messages considered, each truncated to 500 chars"
  - "Rationale/consequences can be inferred, alternatives require explicit mention"

patterns-established:
  - "Structured prompt with JSON output format for extraction tasks"
  - "Handle markdown code blocks in LLM responses"
  - "Log has_rich_context indicator for observability"

issues-created: []

# Metrics
duration: 12min
completed: 2026-01-25
---

# Phase 40 Plan 03: LLM Rich Context Extraction Summary

**Added LLM extraction for rich context fields (rationale, context, alternatives, consequences) from conversation history**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-25T23:55:00Z
- **Completed:** 2026-01-26T00:07:00Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments

- Added RICH_CONTEXT_EXTRACTION_PROMPT with structured JSON output format
- Implemented extract_rich_context() function for LLM-based extraction
- Added _build_conversation_context() helper for message formatting
- Integrated rich context extraction into decision_extraction_node
- Rich context is passed to DecisionStore.create() for persistence

## Task Commits

Each task was committed atomically:

1. **Task 1: Create rich context extraction prompt** - `1d817ba` (feat)
2. **Task 2: Implement extract_rich_context() function** - `ac31509` (feat)
3. **Task 3: Integrate rich context into decision_extraction_node** - `0b538e3` (feat)

## Files Created/Modified

- `src/graph/nodes/decision_extraction.py` - Extended with LLM extraction for rich context

## Decisions Made

- **Low temperature (0.3)**: For consistent structured JSON output from LLM
- **Best-effort extraction**: Errors are logged but don't block decision creation
- **Context limits**: 3000 chars for conversation, 500 chars per message, max 10 messages
- **Inference rules**:
  - Rationale and consequences can be inferred if not explicitly stated
  - Alternatives require explicit mention in conversation (don't invent them)
- **Markdown handling**: Strip code block wrappers from LLM JSON responses

## Verification Checklist

- [x] RICH_CONTEXT_EXTRACTION_PROMPT is well-structured with JSON format
- [x] extract_rich_context() handles errors gracefully (returns empty dict)
- [x] _build_conversation_context() formats messages correctly with truncation
- [x] decision_extraction_node passes rich context to store.create()
- [x] Decisions are created even if rich context extraction fails
- [x] JSON parsing errors handled with logger.warning

## Deviations from Plan

- Added markdown code block handling (```` ``` ````) in extract_rich_context() since LLMs often wrap JSON in code blocks
- Added has_rich_context indicator to both logging and result dict for observability

## Issues Encountered

None.

## Next Phase Readiness

- Rich context now extracted and stored in database
- decision_extraction_node returns has_rich_context indicator
- Ready for UI rendering (40-04) to display rich context in Slack
- Ready for Jira projection (40-05) to include rich context in tickets

---
*Phase: 40-decision-v2-rich-context*
*Completed: 2026-01-25*
