"""Event deduplication to handle Socket Mode retries."""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory dedupe store with TTL
# Format: {event_key: timestamp}
_processed_events: dict[str, float] = {}

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
