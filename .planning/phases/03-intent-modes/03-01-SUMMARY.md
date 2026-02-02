---
phase: 03-intent-modes
plan: 01
subsystem: llm
tags: [litellm, instructor, pydantic, json-repair, structured-output]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: config.py with pydantic-settings
provides:
  - Provider-agnostic LLM client
  - Structured output with Pydantic validation
  - JSON repair fallback layer
affects: [03-02, 03-03, 03-04, 03-05, 03-06]

# Tech tracking
tech-stack:
  added: [litellm, instructor, json-repair]
  patterns: [instructor-patched-litellm, safe-json-parsing]

key-files:
  created: [src/llm/__init__.py, src/llm/client.py]
  modified: [pyproject.toml, src/config.py]

key-decisions:
  - "gemini/gemini-2.0-flash as default model"
  - "Temperature 0.1 for deterministic output"
  - "2 retries for validation failures"

patterns-established:
  - "LiteLLM + Instructor for all LLM calls"
  - "safe_parse_json for fallback JSON repair"

issues-created: []

# Metrics
duration: 3min
completed: 2026-02-02
---

# Phase 3 Plan 01: LLM Dependencies & Client Summary

**Provider-agnostic LLM client using LiteLLM + Instructor with Pydantic structured output and JSON repair fallback**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-02T23:23:10Z
- **Completed:** 2026-02-02T23:26:37Z
- **Tasks:** 4
- **Files modified:** 4

## Accomplishments

- LiteLLM, Instructor, and json-repair dependencies added to project
- LLM configuration settings integrated into pydantic-settings config
- Provider-agnostic LLM client with cached Instructor-patched LiteLLM
- Structured completion function with automatic retry and Pydantic validation
- JSON repair fallback for malformed LLM responses

## Task Commits

Each task was committed atomically:

1. **Task 1: Add LLM dependencies to pyproject.toml** - `17fc665` (chore)
2. **Task 2: Add LLM settings to config** - `15b2aa4` (feat)
3. **Task 3: Create LLM client module structure** - `34eec1b` (feat)
4. **Task 4: Create LLM client with Instructor integration** - `307e928` (feat)

## Files Created/Modified

- `pyproject.toml` - Added litellm>=1.57, instructor>=1.8, json-repair>=0.30
- `src/config.py` - LLM settings (provider, model, api_key, temperature, max_retries) and llm_model_full property
- `src/llm/__init__.py` - Module exports for get_llm_client, structured_completion, safe_parse_json
- `src/llm/client.py` - LiteLLM + Instructor client implementation with JSON repair

## Decisions Made

- **Default to Gemini provider** - gemini/gemini-2.0-flash as default model per RESEARCH.md recommendation
- **Low temperature for classification** - 0.1 for deterministic output in intent routing
- **2 retries for validation** - Balance between reliability and latency
- **Sync client** - instructor.from_litellm(litellm.completion) returns sync client; structured_completion is not async to match

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- LLM client ready for intent classification in 03-02
- Structured output pattern established for schema validation
- JSON repair available as fallback layer

---
*Phase: 03-intent-modes*
*Completed: 2026-02-02*
