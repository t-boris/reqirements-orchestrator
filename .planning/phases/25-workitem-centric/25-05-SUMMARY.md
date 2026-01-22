---
phase: 25-workitem-centric
plan: 05
subsystem: database, state-management

tags: [postgresql, pydantic, langgraph, state-separation, duplicate-detection]

requires:
  - phase: 25-02
    provides: OPS intent routing
  - phase: 25-03
    provides: CHANGE_REQUEST intent
  - phase: 25-04
    provides: ReviewArtifact persistence

provides:
  - Separated ChannelState and ThreadState models (Git model)
  - Channel-first duplicate detection
  - ChannelStateStore and ThreadStateStore persistence
  - Duplicate UI with source indicator (channel vs jira)
  - Backward compatibility helpers for state migration

affects: [future-workitem-flows, jira-sync, commit-log]

tech-stack:
  added: []
  patterns:
    - "Channel = Repository pattern (owns registry)"
    - "Thread = Working Tree pattern (exploration space)"
    - "Channel-first duplicate detection (local before remote)"

key-files:
  created:
    - src/graph/state.py
    - src/db/channel_state_store.py
    - src/db/thread_state_store.py
  modified:
    - src/__main__.py
    - src/graph/runner.py
    - src/graph/nodes/decision.py
    - src/slack/blocks/duplicates.py
    - src/graph/__init__.py
    - src/db/__init__.py

key-decisions:
  - "ChannelState owns registry (workitem_ids, commit_ids, artifact_ids)"
  - "ThreadState is ephemeral exploration space (draft, questions, binding)"
  - "Channel-first duplicate detection: check local registry before Jira"
  - "Skip Jira search if high-confidence (>85%) local match found"
  - "Source indicator in duplicate UI: 'Channel Registry' vs 'Jira'"

patterns-established:
  - "State separation: channel_state and thread_state as separate models"
  - "Load/save pattern: GraphRunner loads separated state on init, saves after execution"
  - "Backward compat helpers: migrate_flat_to_separated(), flatten_separated_state()"

issues-created: []

duration: 18min
completed: 2026-01-22
---

# Phase 25: WorkItem-Centric Architecture Plan 5 Summary

**Separated ChannelState and ThreadState models with channel-first duplicate detection implementing Git model architecture**

## Performance

- **Duration:** 18 min
- **Started:** 2026-01-22T15:04:41Z
- **Completed:** 2026-01-22T15:23:00Z
- **Tasks:** 8
- **Files created:** 3
- **Files modified:** 5

## Accomplishments

- Created separated ChannelState (repository) and ThreadState (working tree) models following Git model
- Built ChannelStateStore and ThreadStateStore for persistence with CRUD operations
- Implemented channel-first duplicate detection (local registry before Jira)
- Added source indicator in duplicate UI showing where match was found
- Graph runner now loads/saves separated state on each execution
- Exported backward compatibility helpers for gradual migration

## Task Commits

Each task was committed atomically:

1. **Task 1: Create separated state models** - `bb4baec` (feat)
2. **Task 2: Create ChannelStateStore** - `5931a70` (feat)
3. **Task 3: Create ThreadStateStore** - `c6248e5` (feat)
4. **Task 4: Create state tables at startup** - `a6cf9b7` (feat)
5. **Task 5: Reorder duplicate detection to channel-first** - `60b0fc8` (feat)
6. **Task 6: Update duplicate UI to show source** - `6d99956` (feat)
7. **Task 7: Update graph to load/save separated state** - `3981ab5` (feat)
8. **Task 8: Add backward compatibility helpers** - `fc8d936` (feat)

## Files Created/Modified

**Created:**
- `src/graph/state.py` - ChannelState, ThreadState, AgentState models with backward compat helpers
- `src/db/channel_state_store.py` - Channel state persistence (registry, settings, activity)
- `src/db/thread_state_store.py` - Thread state persistence (draft, questions, binding)

**Modified:**
- `src/__main__.py` - Create state tables at startup
- `src/graph/runner.py` - Load/save separated state in graph execution
- `src/graph/nodes/decision.py` - Channel-first duplicate detection
- `src/slack/blocks/duplicates.py` - Source indicator in duplicate UI
- `src/graph/__init__.py` - Export state models and helpers
- `src/db/__init__.py` - Export state stores

## Decisions Made

1. **ChannelState as Repository:** Channel owns the registry of workitems, commits, and artifacts. This reflects the Git model where the repo is the source of truth.

2. **ThreadState as Working Tree:** Thread state is ephemeral exploration space with draft, pending questions, and optional binding to a workitem. Clean separation from channel truth.

3. **Channel-First Duplicate Detection:** Check local WorkItem registry before Jira. If high-confidence match (>85%) found locally, skip Jira search. This reflects "check local before remote" principle.

4. **Source Indicator in UI:** Show "Channel Registry" or "Jira" in duplicate UI so users know where match was found and understand the data flow.

5. **Backward Compatibility:** Provide migration helpers (migrate_flat_to_separated, flatten_separated_state) for gradual adoption. Runner continues without separated state on error.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Phase 25 complete: All 5 plans executed
- v1.2 milestone progressing well
- State separation foundation ready for future workitem-centric flows
- Channel-first pattern established for duplicate detection and future Jira sync

---
*Phase: 25-workitem-centric*
*Completed: 2026-01-22*
