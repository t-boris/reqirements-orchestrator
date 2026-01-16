---
phase: 21-jira-sync
plan: 05
subsystem: slack
tags: [jira, slack, decision-linking, architecture-decisions]

# Dependency graph
requires:
  - phase: 21-01
    provides: ChannelIssueTracker for finding tracked issues
  - phase: 21-04
    provides: SyncEngine and channel_decisions table
  - phase: 14
    provides: Decision approval flow and build_decision_blocks
provides:
  - DecisionLinker service for connecting decisions to Jira
  - Auto-update Jira when single match found
  - Selection UI for multiple matches
  - Manual linking via button on decision posts
  - Decision tracking in channel_decisions table
affects: [sync-engine, decision-flow, jira-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - DecisionLinker service pattern for Jira integration
    - Non-blocking decision linking (failures don't affect decision post)
    - UPSERT for channel_decisions table

key-files:
  created:
    - src/slack/decision_linker.py
    - src/slack/handlers/decision_link.py
  modified:
    - src/slack/handlers/dispatch.py
    - src/slack/blocks/decisions.py
    - src/slack/router.py
    - src/slack/handlers/__init__.py

key-decisions:
  - "Default mode: add_comment (safest approach for Jira updates)"
  - "Non-blocking: failures don't affect decision posting to channel"
  - "Single match auto-updates, multiple matches prompt user"
  - "Decision posts include Link to Jira button for retroactive linking"
  - "Decisions tracked in channel_decisions for sync engine integration"

patterns-established:
  - "find_related_issues ranking: explicit keys > thread binding > keyword matches"
  - "UPSERT pattern for channel_decisions table creation and updates"

issues-created: []

# Metrics
duration: 15min
completed: 2026-01-16
---

# Phase 21 Plan 05: Decision-to-Jira Linking Summary

**DecisionLinker service auto-updates Jira when architecture decisions are approved, with selection UI for multiple matches and manual linking via button**

## Performance

- **Duration:** 15 min
- **Started:** 2026-01-16T10:30:00Z
- **Completed:** 2026-01-16T10:45:00Z
- **Tasks:** 5
- **Files modified:** 6

## Accomplishments

- DecisionLinker finds related issues using: explicit keys > thread binding > keyword matches
- Auto-update when single high-confidence match; selection UI for multiple matches
- "Link to Jira Ticket" button on decision posts for retroactive linking
- Decisions tracked in channel_decisions table with "decision" label in Jira
- Formatted Jira comments with heading, topic, decision, date, and Slack link

## Task Commits

Each task was committed atomically:

1. **Task 1: Create DecisionLinker service** - `a0fd9a6` (feat)
2. **Task 2: Hook into approval flow** - `0847288` (feat)
3. **Task 3: Build decision link prompt UI** - `edcefad` (feat)
4. **Task 4: Add manual decision linking via button** - `eca7937` (feat)
5. **Task 5: Add decision history to issue** - `9395a52` (feat)

## Files Created/Modified

- `src/slack/decision_linker.py` - DecisionLinker service: find_related_issues, format_decision_for_jira, apply_decision_to_issue, add_label_if_not_exists, record_decision_sync
- `src/slack/handlers/decision_link.py` - Button handlers: handle_link_decision, handle_skip_decision_link, handle_decision_link_prompt
- `src/slack/handlers/dispatch.py` - _link_decision_to_jira, _prompt_decision_link functions for approval flow
- `src/slack/blocks/decisions.py` - Added show_link_button param and "Link to Jira Ticket" button
- `src/slack/router.py` - Registered link_decision_*, skip_decision_link, decision_link_prompt actions
- `src/slack/handlers/__init__.py` - Exported new handlers

## Decisions Made

- **add_comment as default mode**: Safest approach - doesn't modify ticket description
- **Non-blocking linking**: Decision posts to channel even if Jira update fails
- **Single vs multiple match logic**: Single match auto-updates, multiple prompts user
- **Button on decision posts**: Allows retroactive linking of already-posted decisions
- **channel_decisions tracking**: Integrates with sync engine for bidirectional sync

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Decision-to-Jira linking complete
- Phase 21 (Jira Sync & Management) complete
- Ready for verification with `/gsd:verify-work 21`

---
*Phase: 21-jira-sync*
*Completed: 2026-01-16*
