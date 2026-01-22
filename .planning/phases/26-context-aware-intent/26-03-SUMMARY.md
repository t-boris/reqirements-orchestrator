---
phase: 26-context-aware-intent
plan: 03
subsystem: extraction
tags: [llm, extraction, draft, issue-type, scope]

# Dependency graph
requires:
  - phase: 26-01
    provides: IssueType and RequestedScope enums in TicketDraft
provides:
  - issue_type extraction from user messages
  - requested_scope extraction from user messages
  - title prefix cleanup for clean draft titles
affects: [26-04-decision-node, draft-preview, jira-creation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - enum parsing with validation in extraction node
    - defensive title cleanup for LLM output

key-files:
  created: []
  modified:
    - src/graph/nodes/extraction.py

key-decisions:
  - "Pop extracted fields before patching to prevent double assignment"
  - "Handle both title-case and uppercase type prefixes"

patterns-established:
  - "Parse enum fields with try/except and warn on invalid values"

issues-created: []

# Metrics
duration: 2min
completed: 2026-01-22
---

# Phase 26 Plan 03: Extraction Scope Signals Summary

**Extraction node now detects issue_type (epic/story/task/bug) and requested_scope (epics_only/full_plan/single_item) from user messages, plus strips type prefixes from titles**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-22T20:05:04Z
- **Completed:** 2026-01-22T20:07:01Z
- **Tasks:** 4
- **Files modified:** 1

## Accomplishments

- Both EXTRACTION_PROMPT and EXTRACTION_PROMPT_WITH_REFERENCE now include issue_type and requested_scope fields
- Extraction node parses these fields from LLM JSON response into proper enums
- Title cleanup removes "Epic:", "Story:", "Task:", "Bug:" prefixes that LLM might still add
- Backward compatible - existing extractions continue to work

## Task Commits

Each task was committed atomically:

1. **Task 1: Update EXTRACTION_PROMPT to include issue_type and scope** - `de1343b` (feat)
2. **Task 2: Update EXTRACTION_PROMPT_WITH_REFERENCE similarly** - `70a1fb6` (feat)
3. **Task 3: Handle issue_type and scope in extraction response parsing** - `38ea741` (feat)
4. **Task 4: Strip "Epic:" prefix from extracted titles** - `d9698ce` (feat)

## Files Created/Modified

- `src/graph/nodes/extraction.py` - Added issue_type/requested_scope to prompts and parsing

## Decisions Made

- Pop fields from extracted dict before patching to avoid double assignment
- Handle both title-case (Epic:) and uppercase (EPIC:) prefixes defensively
- Log successful extractions at info level, invalid values at warning level

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Extraction now populates issue_type and requested_scope on TicketDraft
- Ready for 26-04 (draft continuity rule in decision node)
- Decision node can now use these fields to route appropriately

---
*Phase: 26-context-aware-intent*
*Completed: 2026-01-22*
