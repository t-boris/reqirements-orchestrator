---
phase: 21-jira-sync
plan: 03
subsystem: graph
tags: [intent, jira, natural-language, commands]

# Dependency graph
requires:
  - phase: 21-01
    provides: ChannelIssueTracker for contextual target resolution
  - phase: 21-02
    provides: PinnedBoardManager for board refresh after changes
provides:
  - JIRA_COMMAND intent classification
  - JiraCommandNode for command processing
  - Natural language Jira commands with confirmation
  - Field value normalization (priority, status, assignee)
affects: [21-04, 21-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Contextual target resolution (thread binding, channel tracker, conversation)
    - Command confirmation flow with Slack buttons
    - Field normalization mapping

key-files:
  created:
    - src/graph/nodes/jira_command.py
    - src/slack/handlers/jira_commands.py
  modified:
    - src/graph/intent.py
    - src/graph/graph.py
    - src/graph/nodes/__init__.py
    - src/slack/handlers/dispatch.py
    - src/slack/handlers/__init__.py
    - src/slack/router.py

key-decisions:
  - "JIRA_COMMAND separate from TICKET_ACTION: modify fields vs create items"
  - "Contextual resolution order: thread binding > single tracked > most recent in conversation"
  - "Delete requires danger-styled warning confirmation"

patterns-established:
  - "Command confirmation pattern: show before/after, Confirm/Cancel buttons"
  - "Field normalization pattern: mapping + API validation"

issues-created: []

# Metrics
duration: 18min
completed: 2026-01-16
---

# Phase 21 Plan 03: Natural Language Commands Summary

**Natural language Jira commands with JIRA_COMMAND intent, contextual target resolution, confirmation flow, and field normalization.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-01-16T19:47:00Z
- **Completed:** 2026-01-16T20:05:24Z
- **Tasks:** 4
- **Files modified:** 8

## Accomplishments

- Added JIRA_COMMAND intent type for natural language Jira management commands
- Created JiraCommandNode that resolves contextual targets ("that ticket") to actual issue keys
- Built confirmation UI with before/after values and Confirm/Cancel buttons
- Implemented field value normalization (priority, status, assignee)
- Integrated with channel tracker for contextual target resolution

## Task Commits

Each task was committed atomically:

1. **Task 1: Add JIRA_COMMAND intent classification** - `22752b8` (feat)
2. **Task 2: Create JiraCommandNode** - `c358a36` (feat)
3. **Task 3: Add command confirmation and execution handlers** - `f4ecffb` (feat)
4. **Task 4: Add field value normalization** - `bde2865` (feat)

## Files Created/Modified

- `src/graph/intent.py` - Added JIRA_COMMAND to IntentType, extended IntentResult with command fields
- `src/graph/nodes/jira_command.py` - New node for processing JIRA_COMMAND intents with normalization
- `src/graph/nodes/__init__.py` - Export jira_command_node
- `src/graph/graph.py` - Added jira_command_flow routing
- `src/slack/handlers/jira_commands.py` - New handler file for command confirmation and execution
- `src/slack/handlers/dispatch.py` - Route jira_command_confirm and jira_command_ambiguous
- `src/slack/handlers/__init__.py` - Export new handlers
- `src/slack/router.py` - Register button handlers

## Decisions Made

1. **JIRA_COMMAND vs TICKET_ACTION distinction:**
   - JIRA_COMMAND = modify existing field values (priority, status, assignee)
   - TICKET_ACTION = create new items linked to ticket (stories, subtasks, comments)
   - Rationale: Clear separation of "change field" vs "add content"

2. **Contextual target resolution priority:**
   - 1st: Thread binding (if in thread with linked ticket)
   - 2nd: Single tracked issue in channel
   - 3rd: Most recently mentioned issue in conversation
   - Rationale: Most specific context wins, fallback to channel-wide

3. **Delete confirmation with danger styling:**
   - Red "Delete" button instead of green "Confirm"
   - Explicit warning about irreversibility
   - Rationale: Destructive actions need extra friction

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- JIRA_COMMAND intent detection ready for natural language commands
- Confirmation flow in place for safe command execution
- Board refresh triggered after successful changes
- Ready for 21-04 (Smart Sync Engine) which will use the command infrastructure

---
*Phase: 21-jira-sync*
*Completed: 2026-01-16*
