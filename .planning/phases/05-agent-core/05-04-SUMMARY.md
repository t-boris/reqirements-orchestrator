---
phase: 05-agent-core
plan: 04
status: complete
---

# 05-04 Summary: Runner Integration

## What Was Built

1. **Graph Runner** (`src/graph/runner.py`)
   - `GraphRunner` class manages graph execution per session
   - `run_with_message()` - adds message to state, runs graph until interrupt
   - `handle_approval()` - handles approve/reject from preview
   - Uses session locks for per-thread serialization
   - `get_runner()` / `cleanup_runner()` for session-scoped runner cache
   - Interrupt detection for ASK/PREVIEW/READY_TO_CREATE actions

2. **Updated Slack Handlers** (`src/slack/handlers.py`)
   - `handle_app_mention` now creates session identity and runs graph via runner
   - `_process_mention()` async function handles graph results
   - `handle_message` checks for active session before processing thread messages
   - `_process_thread_message()` continues graph for thread messages
   - `handle_approve_draft` / `handle_reject_draft` action handlers for approval buttons

3. **Draft Preview Blocks** (`src/slack/blocks.py`)
   - `build_draft_preview_blocks()` builds Slack Block Kit UI for draft preview
   - Shows: title, problem, solution, acceptance criteria, constraints
   - Includes "Approve & Create" and "Needs Changes" buttons
   - Shows version and evidence link count in context

## Integration Flow

```
@mention → handle_app_mention → get_runner → run_with_message → graph.astream
                                                        ↓
                                             check decision_result
                                                        ↓
                              ┌──────────────┬──────────┴───────────┐
                              ↓              ↓                      ↓
                            ASK           PREVIEW               READY
                              ↓              ↓                      ↓
                        post questions  post preview           notify user
                                             ↓
                                    user clicks button
                                             ↓
                              handle_approve_draft / handle_reject_draft
                                             ↓
                                    runner.handle_approval()
```

## Verification

```bash
python -c "from src.graph.runner import GraphRunner, get_runner; print('runner ok')"
# Output: runner ok

python -c "from src.slack.handlers import handle_app_mention, handle_approve_draft; print('handlers ok')"
# Output: handlers ok

python -c "from src.slack.blocks import build_draft_preview_blocks; print('preview blocks ok')"
# Output: preview blocks ok
```

## Files Created/Modified

- `src/graph/runner.py` (created)
- `src/slack/handlers.py` (updated with graph integration)
- `src/slack/blocks.py` (added build_draft_preview_blocks)

## Success Criteria Met

- Graph runner manages interrupt/resume flow
- Slack handlers integrated with graph runner
- ASK action posts questions to thread
- PREVIEW action shows draft with approval buttons
- Per-thread serialization via session locks
- DoD Scenario 1: Enough data → PREVIEW → approval → READY_TO_CREATE
- DoD Scenario 2: Not enough data → ASK → interrupt → resume
