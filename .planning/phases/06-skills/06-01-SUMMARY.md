---
phase: 06-skills
plan: 01
subsystem: agent
tags: [slack, skills, llm, async, pydantic]

# Dependency graph
requires:
  - phase: 05-agent-core
    provides: GraphRunner with interrupt/resume, DecisionResult with questions[]
provides:
  - ask_user skill for posting questions to Slack threads
  - QuestionSet/AskResult models for question tracking
  - Semantic answer matching with LLM
  - Re-ask logic with max 2 attempts
affects: [06-02-preview-ticket, 07-jira-sync]

# Tech tracking
tech-stack:
  added: []
  patterns: [skill-as-async-function, semantic-answer-matching, reask-limit]

key-files:
  created:
    - src/skills/__init__.py
    - src/skills/ask_user.py
    - src/skills/answer_matcher.py
  modified:
    - src/schemas/state.py
    - src/graph/runner.py
    - src/graph/nodes/extraction.py
    - src/graph/nodes/decision.py

key-decisions:
  - "Skills are async functions with explicit parameters (not graph nodes)"
  - "Yes/No button detection via question prefix heuristic (Is/Are/Do/Does/Should/Will)"
  - "MAX_REASK_COUNT=2 to prevent infinite loops"
  - "TypedDict-compatible question tracking (dict instead of Pydantic model in state)"

patterns-established:
  - "Skill pattern: async function with Slack client as parameter"
  - "Answer matching: LLM-based semantic correlation of response to questions"
  - "Re-ask flow: unanswered questions tracked and re-asked up to limit"

issues-created: []

# Metrics
duration: 5min
completed: 2026-01-14
---

# Phase 6 Plan 1: ask_user Skill Summary

**ask_user skill with semantic answer matching and max 2 re-asks for interrupt/resume flow**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-14T18:57:43Z
- **Completed:** 2026-01-14T19:02:57Z
- **Tasks:** 5
- **Files modified:** 7

## Accomplishments

- Created skills package with ask_user skill for posting questions to Slack
- Implemented QuestionSet and AskResult Pydantic models for question tracking
- Added semantic answer matching using LLM to correlate user responses with questions
- Implemented re-ask logic with max 2 attempts before proceeding with partial info
- Integrated question tracking into AgentState and GraphRunner

## Task Commits

Each task was committed atomically:

1. **Task 1: Create skill module structure** - `7985018` (feat)
2. **Task 2: Implement ask_user skill** - included in Task 1
3. **Task 3: Add question tracking to state** - `1d1b9d8` (feat)
4. **Task 4: Implement semantic answer matching** - `c8e82e2` (feat)
5. **Task 5: Implement re-ask logic** - `87c0b94` (feat)

## Files Created/Modified

- `src/skills/__init__.py` - Skills package with exports
- `src/skills/ask_user.py` - ask_user skill with QuestionSet, AskResult models
- `src/skills/answer_matcher.py` - LLM-based semantic answer matching
- `src/schemas/state.py` - Added pending_questions, question_history fields
- `src/graph/runner.py` - Question tracking methods (store/clear/get)
- `src/graph/nodes/extraction.py` - Integration with answer matcher
- `src/graph/nodes/decision.py` - Re-ask logic with MAX_REASK_COUNT

## Decisions Made

1. **Skills as async functions** - Skills are standalone async functions with explicit parameters (Slack client, channel, thread_ts), not graph nodes. This keeps them deterministic and testable.
2. **Yes/No button heuristic** - Questions starting with Is/Are/Do/Does/Should/Will get inline Yes/No buttons automatically.
3. **Max 2 re-asks** - After 2 re-ask attempts, proceed with partial info rather than infinite loop.
4. **TypedDict compatibility** - Question tracking uses dict[str, Any] in state (not Pydantic) for LangGraph TypedDict compatibility.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- ask_user skill complete and ready for handler integration
- Question tracking infrastructure in place
- Ready for 06-02: preview_ticket skill

---
*Phase: 06-skills*
*Completed: 2026-01-14*
