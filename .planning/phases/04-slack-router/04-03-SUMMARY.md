---
phase: 04-slack-router
plan: 03
status: completed
completed_at: 2026-01-14
---

# Plan 04-03 Summary: Session Identity and Deduplication

## Objective

Created session model with idempotency and per-thread serialization to prevent duplicate event processing and race conditions in thread sessions.

## What Was Done

### Task 1: Session Identity Utilities (src/slack/session.py)

Created `SessionIdentity` dataclass and per-session locking:

- **SessionIdentity**: Dataclass holding `team_id`, `channel_id`, and `thread_ts`
- **session_id property**: Canonical format `{team_id}:{channel_id}:{thread_ts}`
- **from_event() classmethod**: Extracts identity from Slack event, uses `thread_ts` if available or falls back to `ts`
- **get_session_lock()**: Returns or creates asyncio.Lock for a session ID
- **with_session_lock()**: Async context manager for acquiring session lock
- **cleanup_session_lock()**: Removes lock when session is closed

### Task 2: Event Deduplication (src/slack/dedup.py)

Created event deduplication module to handle Socket Mode retries:

- **_get_event_key()**: Extracts unique key from event (prefers `event_id`, falls back to `client_msg_id`, then `channel:ts`)
- **is_duplicate()**: Checks if event was already processed, includes lazy TTL cleanup
- **mark_processed()**: Records event as processed with current timestamp
- **clear_dedup_store()**: Utility function for testing
- **DEDUP_TTL_SECONDS**: 5-minute TTL for processed events

### Task 3: Epic ID Field (src/db/models.py)

Added `epic_id` field to `ThreadSession` model:

```python
epic_id: Optional[str] = Field(
    default=None,
    description="Linked Epic Jira key (e.g., PROJ-50)",
)
```

This enables Rule 1: Context Binding - every session can be bound to an Epic.

## Files Modified

| File | Action | Description |
|------|--------|-------------|
| `src/slack/session.py` | Created | Session identity and per-session locking |
| `src/slack/dedup.py` | Created | Event deduplication with TTL |
| `src/db/models.py` | Modified | Added `epic_id` field to ThreadSession |

## Verification Results

All verification commands passed:

- `python -c "from src.slack.session import SessionIdentity"` - OK
- `python -c "from src.slack.dedup import is_duplicate"` - OK
- `SessionIdentity.from_event()` extracts canonical ID correctly
- Dedup correctly identifies duplicate events
- `ThreadSession.epic_id` field present

## Key Design Decisions

1. **Canonical session ID format**: `team:channel:thread_ts` allows unique identification across workspaces
2. **In-memory dedup store**: Simple, fast, with lazy TTL cleanup to prevent unbounded growth
3. **Per-session locks**: Prevent race conditions when multiple events arrive for same thread
4. **Event key hierarchy**: `event_id` > `client_msg_id` > `channel:ts` for reliable deduplication

## Dependencies Satisfied

This plan provides foundations for:
- Plan 04-02 (Message Handlers): Uses SessionIdentity and dedup
- Plan 04-04 (Graph Integration): Uses session locks for serialization
- Future context binding: epic_id field ready for use
