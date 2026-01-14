"""Event deduplication to handle Socket Mode retries and button clicks."""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory dedupe store with TTL
# Format: {event_key: timestamp}
_processed_events: dict[str, float] = {}

# Button click dedupe store (separate from events)
# Format: {button_key: timestamp}
_processed_buttons: dict[str, float] = {}

# TTL for processed events (5 minutes)
DEDUP_TTL_SECONDS = 300


def _get_event_key(event: dict) -> Optional[str]:
    """Extract unique key from event for deduplication.

    Uses event_id if available, falls back to client_msg_id or message ts.
    """
    # Prefer event_id (most reliable)
    if event_id := event.get("event_id"):
        return f"event:{event_id}"

    # Fallback to client_msg_id (for messages)
    if client_msg_id := event.get("client_msg_id"):
        return f"msg:{client_msg_id}"

    # Last resort: channel + ts
    channel = event.get("channel")
    ts = event.get("ts")
    if channel and ts:
        return f"ts:{channel}:{ts}"

    return None


def is_duplicate(event: dict) -> bool:
    """Check if event was already processed.

    Returns True if duplicate (should skip), False if new.
    """
    key = _get_event_key(event)
    if not key:
        # Can't dedupe without key, assume not duplicate
        return False

    now = time.time()

    # Clean expired entries (lazy cleanup)
    expired = [k for k, t in _processed_events.items() if now - t > DEDUP_TTL_SECONDS]
    for k in expired:
        del _processed_events[k]

    if key in _processed_events:
        logger.debug(f"Duplicate event detected: {key}")
        return True

    return False


def mark_processed(event: dict) -> None:
    """Mark event as processed.

    Call after successfully processing event.
    """
    key = _get_event_key(event)
    if key:
        _processed_events[key] = time.time()
        logger.debug(f"Marked event processed: {key}")


def clear_dedup_store() -> None:
    """Clear all entries (for testing)."""
    _processed_events.clear()
    _processed_buttons.clear()


# --- Button Click Deduplication ---


def is_button_duplicate(action_id: str, user_id: str, button_value: str) -> bool:
    """Check if button click was already processed.

    Used to handle Slack retries and rage-clicks on approval buttons.

    Args:
        action_id: Button action ID (e.g., "approve_draft")
        user_id: User who clicked
        button_value: Button value (session_id:draft_hash)

    Returns:
        True if duplicate (should skip), False if new
    """
    key = f"btn:{action_id}:{user_id}:{button_value}"

    now = time.time()

    # Clean expired entries (lazy cleanup)
    expired = [k for k, t in _processed_buttons.items() if now - t > DEDUP_TTL_SECONDS]
    for k in expired:
        del _processed_buttons[k]

    if key in _processed_buttons:
        logger.debug(f"Duplicate button click: {key}")
        return True

    return False


def mark_button_processed(action_id: str, user_id: str, button_value: str) -> None:
    """Mark button click as processed.

    Call after successfully processing button click.
    """
    key = f"btn:{action_id}:{user_id}:{button_value}"
    _processed_buttons[key] = time.time()
    logger.debug(f"Marked button processed: {key}")


def try_process_button(action_id: str, user_id: str, button_value: str) -> bool:
    """Atomic check-and-mark for button clicks.

    Combines duplicate check and marking into one operation.
    First call wins - subsequent calls return False.

    Args:
        action_id: Button action ID
        user_id: User who clicked
        button_value: Button value

    Returns:
        True if this is the first click (should process)
        False if duplicate (should skip)
    """
    if is_button_duplicate(action_id, user_id, button_value):
        return False

    mark_button_processed(action_id, user_id, button_value)
    return True
