---
phase: 06-skills
plan: 02
subsystem: slack
tags: [slack, buttons, idempotency, preview, approval, hash, postgresql]

# Dependency graph
requires:
  - phase: 05-agent-core
    provides: TicketDraft model with version field
  - phase: 06-skills/01
    provides: Skills package structure
provides:
  - preview_ticket skill with version checking
  - ApprovalStore for idempotent approval records
  - Version-checked approval handlers
affects: [07-jira-integration, slack-handlers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Idempotency via unique DB constraint + in-memory dedup"
    - "Version hash embedded in button values"
    - "Two-layer dedup: in-memory for retries, DB for races"

key-files:
  created:
    - src/skills/preview_ticket.py
    - src/db/approval_store.py
  modified:
    - src/skills/__init__.py
    - src/db/__init__.py
    - src/slack/blocks.py
    - src/slack/handlers.py
    - src/slack/dedup.py

key-decisions:
  - "SHA256[:8] hash of title|problem|acceptance_criteria for version checking"
  - "Button value format: session_id:draft_hash for version embedding"
  - "First-wins with ON CONFLICT DO NOTHING for approval records"
  - "Separate dedup store for buttons (5-min TTL)"

patterns-established:
  - "Version-checked approvals: compute hash, embed in button, validate on click"
  - "Two-layer idempotency: in-memory catches retries, DB catches races"
  - "Approved/rejected state: update message to disable buttons, show status"

issues-created: []

# Metrics
duration: 5min
completed: 2026-01-14
---

# Phase 6 Plan 02: preview_ticket Skill Summary

**preview_ticket skill with SHA256 version checking, PostgreSQL approval records, and two-layer idempotency for button clicks**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-14T19:05:07Z
- **Completed:** 2026-01-14T19:10:00Z
- **Tasks:** 5
- **Files modified:** 7

## Accomplishments
- preview_ticket skill posts draft preview with embedded version hash in buttons
- ApprovalStore with unique constraint on (session_id, draft_hash) for first-wins semantics
- Version-checked approval handler that detects draft changes and requires re-review
- Idempotent button handling with in-memory dedup (Slack retries) + DB constraint (races)
- Preview message updated after approval/rejection to show final state

## Task Commits

Each task was committed atomically:

1. **Task 1: Create preview_ticket skill module** - `1354456` (feat)
2. **Task 2: Update preview blocks with version hash and evidence** - `c101d40` (feat)
3. **Task 3: Create approval records table and store** - `72ffc63` (feat)
4. **Task 4: Implement version-checked approval handler** - `fc94073` (feat)
5. **Task 5: Implement idempotent button handling** - `e2afa3d` (feat)

## Files Created/Modified
- `src/skills/preview_ticket.py` - PreviewResult model, compute_draft_hash(), preview_ticket() skill
- `src/skills/__init__.py` - Export preview_ticket, PreviewResult, compute_draft_hash
- `src/db/approval_store.py` - ApprovalRecord model, ApprovalStore with CRUD operations
- `src/db/__init__.py` - Export ApprovalStore, ApprovalRecord
- `src/slack/blocks.py` - build_draft_preview_blocks_with_hash() with evidence and hash
- `src/slack/handlers.py` - Version-checked handle_approve_draft(), idempotent handle_reject_draft()
- `src/slack/dedup.py` - Button click dedup: try_process_button(), separate store

## Decisions Made
- SHA256[:8] hash of "title|problem|comma-joined-ACs" for version checking
- Button value format session_id:draft_hash embeds version for later validation
- ON CONFLICT DO NOTHING in PostgreSQL for first-wins approval semantics
- Separate in-memory store for button clicks (5-minute TTL) vs event dedup

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- preview_ticket skill ready for integration with graph runner
- Approval flow complete with version checking and idempotency
- Ready for Phase 6 Plan 03: edit modal for rejected drafts

---
*Phase: 06-skills*
*Completed: 2026-01-14*
