---
phase: 21-jira-sync
plan: 04
type: summary
completed: 2026-01-16
commits: 5
---

# Plan 21-04: Smart Sync Engine

## Objective

Create smart sync engine for bidirectional Jira synchronization. "@Maro update Jira issues" triggers smart sync - finds delta between channel decisions and Jira, applies obvious updates automatically, asks about conflicts.

## Tasks Completed

### Task 1: Create SyncEngine with change detection
- Created `src/slack/sync_engine.py` with:
  - `ChangeDetection` dataclass with issue_key, field, values, change_type, confidence
  - `SyncPlan` with auto_apply, needs_review, and in_sync categorization
  - `detect_changes()` fetches tracked issues and compares against Jira
  - `apply_changes()` pushes changes to Jira and updates tracker
  - Confidence-based categorization (>0.8 = auto-apply)
  - Support for status transitions and decision syncing

### Task 2: Add /maro sync command
- Added sync subcommand to /maro in `commands.py`:
  - `/maro sync` - Show pending changes summary
  - `/maro sync --auto` - Apply obvious changes automatically
- Created `src/slack/handlers/sync.py` with:
  - `build_sync_summary_blocks()` for sync UI
  - `handle_sync_apply_all()` applies all auto-apply changes
  - `handle_sync_use_slack/jira()` for conflict resolution
  - `handle_sync_skip/cancel()` for user control

### Task 3: Build conflict resolution UI
- Added full conflict resolution flow:
  - `build_full_conflict_blocks()` with side-by-side version display
  - `handle_sync_merge()` opens modal for manual merging
  - `handle_sync_merge_submit()` applies merged content to Jira
  - Full conflict UI with Use Slack/Use Jira/Merge.../Skip buttons
  - Registered handlers in router.py

### Task 4: Add sync trigger on "@Maro update Jira"
- Added `SYNC_REQUEST` intent type to `intent.py`
- LLM prompt updated with sync examples
- Created `src/graph/nodes/sync_trigger.py`
- Graph routes SYNC_REQUEST -> sync_flow -> sync_trigger -> END
- dispatch.py handles sync_request action

### Task 5: Track decisions as sync sources
- dispatch.py: Record decisions even when no related issues found
- review.py: Add decision recording after approve_architecture button
- Both flows call `DecisionLinker.record_decision_sync()`
- SyncEngine._detect_decision_changes() finds unsynced decisions

## Files Modified

**Created:**
- `src/slack/sync_engine.py` - SyncEngine with change detection
- `src/slack/handlers/sync.py` - Sync command handlers
- `src/graph/nodes/sync_trigger.py` - SYNC_REQUEST intent handler

**Modified:**
- `src/slack/handlers/commands.py` - Added /maro sync subcommand
- `src/slack/handlers/__init__.py` - Export sync handlers
- `src/slack/router.py` - Register sync action handlers
- `src/graph/intent.py` - Added SYNC_REQUEST intent
- `src/graph/graph.py` - Added sync_flow routing
- `src/slack/handlers/dispatch.py` - Handle sync_request, record unlinked decisions
- `src/slack/handlers/review.py` - Record decisions on approve button

## Commits

1. `adbcdd3` - Add SyncEngine with change detection for Jira sync
2. `b896d50` - Add /maro sync command for Jira synchronization
3. `c1db7ba` - Add conflict resolution UI with side-by-side comparison
4. `275308b` - Add sync trigger for '@Maro update Jira' intent
5. `7fe5660` - Track decisions as sync sources for /maro sync

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Confidence threshold 0.8 for auto-apply | High confidence prevents unintended changes |
| Decisions as comments, not description updates | Safest approach, doesn't modify existing content |
| SYNC_REQUEST as separate intent | Bulk sync is distinct from single-ticket JIRA_COMMAND |
| Record unlinked decisions | Enables later linking via /maro sync |

## Success Criteria Met

- [x] SyncEngine detects changes between Slack and Jira
- [x] /maro sync shows categorized changes
- [x] Auto-apply for obvious changes
- [x] Conflict resolution with side-by-side UI
- [x] Natural language sync triggers
- [x] Decisions tracked as sync sources
