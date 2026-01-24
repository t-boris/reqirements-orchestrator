---
phase: 34-file-attachment-processing
plan: 06
subsystem: context-management
tags: [attachments, retrieval, supermode, policy, intent]

# Dependency graph
requires:
  - phase: 34-01
    provides: AttachmentStore and Attachment schema
  - phase: 34-04
    provides: AttachmentChunkStore with full-text search
  - phase: 34-05
    provides: Pin/unpin mechanics and button handlers
provides:
  - AttachmentRetriever with intent-scoped policies
  - AttachmentPolicy enum (6 policies)
  - AttachmentContext dataclass with prompt formatting
  - resolve_attachment_context() for dispatch integration
affects: [34-07, 34-08, context-injection, prompt-building]

# Tech tracking
tech-stack:
  added: []
  patterns: ["intent-scoped-policy", "token-budget-retrieval"]

key-files:
  created: [src/documents/retriever.py]
  modified: [src/graph/state.py, src/slack/handlers/dispatch.py]

key-decisions:
  - "Policy enum covers 6 modes: NONE, PINNED_ONLY, PINNED_RETRIEVAL, PINNED_STRUCTURAL, LOGS_RETRIEVAL, PINNED_CITED"
  - "MODE_POLICIES maps all 5 SuperModes to policies"
  - "Token budgets: 2000 for pinned, 1500 for retrieval, top-5 chunks"
  - "Non-blocking: failures logged but don't break request flow"

patterns-established:
  - "Intent-scoped attachment policies via MODE_POLICIES mapping"
  - "AttachmentContext as dataclass with to_prompt_section() and to_offer_message()"

issues-created: []

# Metrics
duration: 12min
completed: 2026-01-23
---

# Phase 34 Plan 06: Intent-Scoped Attachment Rules Summary

**AttachmentRetriever with policy engine that determines what attachment content to include based on SuperMode (BUILD gets pinned+structural, CHAT gets offer message, THINK gets retrieval)**

## Performance

- **Duration:** 12 min
- **Started:** 2026-01-23T16:30:00Z
- **Completed:** 2026-01-23T16:42:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Created AttachmentRetriever with intent-scoped policies
- Defined AttachmentPolicy enum with 6 inclusion modes
- MODE_POLICIES maps all SuperModes to appropriate policies
- Added attachment_context field to AgentState for graph flow
- Integrated resolve_attachment_context() into dispatch flow

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Attachment Retriever Module** - `e4216b1` (feat)
2. **Task 2: Add Attachment Context to AgentState** - `1a1ee80` (feat)
3. **Task 3: Integrate Retriever into Dispatch** - `f87c41b` (feat)

## Files Created/Modified

- `src/documents/retriever.py` - AttachmentRetriever with policy engine and context formatting
- `src/graph/state.py` - Added attachment_context field to AgentState
- `src/slack/handlers/dispatch.py` - Added resolve_attachment_context() function

## Decisions Made

- **Policy granularity:** 6 policies cover all intent-to-mode mappings with appropriate behavior
- **Token budgets:** 2000 tokens for pinned content, 1500 for retrieval, configurable
- **Chunk retrieval:** Top-5 chunks by default using existing full-text search
- **Log detection:** Filename-based heuristics for OPERATE mode log filtering
- **Non-blocking design:** Attachment resolution failures logged but don't break requests

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Intent-scoped policies complete
- Ready for 34-07: Transparency UI (show what files/sections were used)
- Ready for 34-08: Retrieval Context Injection (inject context into prompts)

---
*Phase: 34-file-attachment-processing*
*Completed: 2026-01-23*
