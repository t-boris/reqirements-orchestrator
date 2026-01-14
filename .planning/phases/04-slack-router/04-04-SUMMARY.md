---
phase: 04-slack-router
plan: 04
status: completed
completed_at: 2026-01-14
---

# Plan 04-04 Summary: Epic Binding Flow

## Objective

Created Epic binding flow with session card UI - implementing Rule 1 (Context Binding) where every thread is bound to an Epic.

## What Was Done

### Task 1: Block Kit Builders (src/slack/blocks.py)

Created Slack Block Kit message builders:

- **build_session_card()**: Builds session card with Epic link, status, and available commands
  - Shows Epic link or "Not linked yet" placeholder
  - Displays session status
  - Lists available commands in context block

- **build_epic_selector()**: Builds Epic selection UI with suggested Epics
  - Shows message preview for context
  - Displays up to 3 suggested Epic buttons
  - Includes "New Epic" button (primary style)
  - Gracefully handles empty suggestions

### Task 2: Epic Binding Flow (src/slack/binding.py)

Created Epic binding logic:

- **suggest_epics()**: Searches for relevant Epics using Zep semantic search
  - Returns list of {key, summary, score} dicts
  - Handles errors gracefully, returns empty list on failure

- **start_binding_flow()**: Initiates Epic binding for new sessions
  - Gets or creates session via SessionStore
  - If already bound, posts session card
  - If unbound, searches for suggestions and posts epic selector

- **bind_epic()**: Binds session to selected Epic
  - Updates session with epic_id via SessionStore
  - Posts session card confirming binding

### Task 3: Action Handlers (src/slack/handlers.py)

Added Epic selection button handlers:

- **handle_epic_selection_sync()**: Synchronous wrapper for Bolt callbacks
- **_handle_epic_selection_async()**: Async implementation that:
  - Extracts epic_key, channel, thread_ts from action body
  - Creates SessionIdentity from context
  - Handles "new" action with placeholder message (Phase 7)
  - Calls bind_epic for existing Epic selection

### Task 4: Router Registration (src/slack/router.py)

Updated router to register action handlers:

- Added regex pattern handler for `select_epic_*` actions
- Uses `re.compile(r"^select_epic_.*")` to match all Epic selection buttons

### Additional: SessionStore Enhancement (src/db/session_store.py)

Added `epic_id` support to SessionStore:

- Added `epic_id` column to table schema
- Added migration for existing tables
- Updated all queries to include `epic_id`
- Added `update_epic()` method for binding Epic to session
- Added `get_or_create()` convenience alias

## Files Modified

| File | Action | Description |
|------|--------|-------------|
| `src/slack/blocks.py` | Created | Block Kit builders for session card and epic selector |
| `src/slack/binding.py` | Created | Epic binding flow with suggestion and selection |
| `src/slack/handlers.py` | Modified | Added epic selection action handlers |
| `src/slack/router.py` | Modified | Register action handlers for select_epic_* pattern |
| `src/db/session_store.py` | Modified | Added epic_id column, update_epic method, migration |

## Verification Results

All verification commands passed:

- `python -c "from src.slack.blocks import build_session_card, build_epic_selector"` - OK
- `python -c "from src.slack.binding import start_binding_flow, bind_epic"` - OK
- `python -c "from src.slack.handlers import handle_epic_selection_sync"` - OK
- `python -c "from src.slack.router import register_handlers"` - OK
- Session card produces 4 blocks with correct structure
- Epic selector produces correct button layout
- SessionStore.update_epic method available

## Key Design Decisions

1. **Sync/Async Handling**: Handler uses sync wrapper with async implementation since Bolt may call from sync context
2. **Graceful Degradation**: Epic search failures return empty list, allowing "New Epic" fallback
3. **Schema Migration**: Added DO block to migrate existing tables without epic_id column
4. **Button Pattern**: Action IDs use `select_epic_{key}` pattern for easy regex matching

## Dependencies Satisfied

This plan implements:
- DoD: session(thread_ts) -> epic_id stored
- DoD: Pinned "Session Card" message in thread with epic link, status, commands
- DoD: LLM-based epic suggestions (via Zep semantic search)

## Future Work

- Phase 7: Implement actual Jira Epic creation for "New Epic" button
- Phase 7: Fetch Epic summary from Jira for session card display
- Configure Jira base URL instead of hardcoded example.com
