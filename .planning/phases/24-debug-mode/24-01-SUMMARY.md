---
phase: 24-debug-mode
plan: 01
subsystem: debug
tags: [pydantic, dataclass, postgres, slack-blocks]

# Dependency graph
requires:
  - phase: 23.2-channel-mode
    provides: ChannelModeStore pattern for per-channel config persistence
provides:
  - DebugModeConfig model for debug state persistence
  - DebugStore for CRUD operations on debug mode
  - DebugCollector for structured debug data collection
affects: [24-02-slash-command, 24-03-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [debug-collector-pattern, dataclass-for-debug-entries]

key-files:
  created:
    - src/db/debug_store.py
    - src/debug/__init__.py
    - src/debug/collector.py
  modified:
    - src/db/models.py

key-decisions:
  - "Use dataclass for DebugEntry/LLMCall (simple value objects, no validation needed)"
  - "Follow ChannelModeStore pattern for DebugStore consistency"
  - "Category-based grouping for debug entries (intent, duplicates, decision, llm, error)"

patterns-established:
  - "DebugCollector accumulates entries during processing, formats at end"
  - "Dual output format: Slack blocks (truncated) + file content (full)"

issues-created: []

# Metrics
duration: 2min
completed: 2026-01-22
---

# Phase 24 Plan 01: Debug Mode Foundation Summary

**DebugModeConfig model, DebugStore with CRUD operations, and DebugCollector dataclass for structured debug output**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-22T14:02:40Z
- **Completed:** 2026-01-22T14:04:57Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added DebugModeConfig Pydantic model with channel_id, enabled, verbosity fields
- Created DebugStore with get, is_enabled, enable, disable methods following ChannelModeStore pattern
- Implemented DebugCollector with DebugEntry and LLMCall dataclasses
- Added to_slack_blocks() for Slack-formatted output with truncation
- Added to_file_content() for full debug dump as text

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DebugModeConfig model to models.py** - `5a5ed59` (feat)
2. **Task 2: Create DebugStore with CRUD operations** - `c39f3a2` (feat)
3. **Task 3: Create DebugCollector dataclass** - `f9a0ee4` (feat)

## Files Created/Modified

- `src/db/models.py` - Added DebugModeConfig Pydantic model
- `src/db/debug_store.py` - DebugStore class with CRUD operations
- `src/debug/__init__.py` - Module exports for DebugCollector
- `src/debug/collector.py` - DebugEntry, LLMCall, DebugCollector classes

## Decisions Made

- Used dataclass for DebugEntry and LLMCall (simple value objects without validation needs)
- Followed ChannelModeStore pattern for DebugStore for codebase consistency
- Category-based grouping for entries: intent, duplicates, decision, llm, error
- Dual output format: truncated Slack blocks + full file attachment

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Foundation components ready for Plan 02 (slash command handler)
- DebugStore can be used by `/maro debug on/off/status` handler
- DebugCollector can be instantiated in dispatch and passed through processing

---
*Phase: 24-debug-mode*
*Completed: 2026-01-22*
