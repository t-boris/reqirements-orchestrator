"""Track actionable bot messages to remove stale buttons.

When bot posts a new message with action buttons, old buttons become irrelevant.
This tracker remembers the last actionable message per thread and helps remove
old buttons when posting new ones.

Phase 39: Remove stale buttons (except pinned messages).
"""
import logging
from dataclasses import dataclass
from typing import Optional

from slack_sdk import WebClient

logger = logging.getLogger(__name__)

# In-memory cache: (channel_id, thread_ts) -> message_ts of last actionable message
_actionable_messages: dict[tuple[str, str], str] = {}


@dataclass
class ActionableMessage:
    """A bot message with action buttons."""

    channel_id: str
    thread_ts: str
    message_ts: str


def track_actionable_message(channel_id: str, thread_ts: str, message_ts: str) -> None:
    """Track a newly posted actionable message.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp (or None for channel-level)
        message_ts: Message timestamp of the actionable message
    """
    key = (channel_id, thread_ts or "")
    _actionable_messages[key] = message_ts
    logger.debug(f"Tracked actionable message: {channel_id}/{thread_ts} -> {message_ts}")


def get_previous_actionable_message(
    channel_id: str, thread_ts: str
) -> Optional[str]:
    """Get the previous actionable message timestamp for this thread.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp

    Returns:
        Previous message_ts if exists, None otherwise
    """
    key = (channel_id, thread_ts or "")
    return _actionable_messages.get(key)


def remove_buttons_from_message(
    client: WebClient,
    channel_id: str,
    message_ts: str,
) -> bool:
    """Remove action buttons from a message, keeping text content.

    Uses conversations.history to get current blocks, then removes action blocks
    and updates the message.

    Args:
        client: Slack WebClient
        channel_id: Channel where message lives
        message_ts: Timestamp of message to update

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get the current message
        result = client.conversations_history(
            channel=channel_id,
            latest=message_ts,
            inclusive=True,
            limit=1,
        )

        if not result.get("messages"):
            logger.warning(f"Message not found: {channel_id}/{message_ts}")
            return False

        message = result["messages"][0]

        # Check if pinned - don't touch pinned messages
        if message.get("pinned_to"):
            logger.debug(f"Skipping pinned message: {message_ts}")
            return False

        # Get current blocks and filter out action blocks
        blocks = message.get("blocks", [])
        if not blocks:
            return False

        # Remove action blocks
        new_blocks = [b for b in blocks if b.get("type") != "actions"]

        # If nothing changed, no update needed
        if len(new_blocks) == len(blocks):
            return False

        # Update the message without action blocks
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=new_blocks,
            text=message.get("text", ""),
        )

        logger.info(f"Removed buttons from message: {channel_id}/{message_ts}")
        return True

    except Exception as e:
        logger.warning(f"Failed to remove buttons from {message_ts}: {e}")
        return False


def clear_old_actionable_and_track_new(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    new_message_ts: str,
) -> None:
    """Clear buttons from previous actionable message and track new one.

    Convenience function that combines:
    1. Remove buttons from previous actionable message (if any)
    2. Track the new message as current actionable

    Args:
        client: Slack WebClient
        channel_id: Channel ID
        thread_ts: Thread timestamp
        new_message_ts: Timestamp of newly posted actionable message
    """
    # Try to clear old message
    old_ts = get_previous_actionable_message(channel_id, thread_ts)
    if old_ts and old_ts != new_message_ts:
        remove_buttons_from_message(client, channel_id, old_ts)

    # Track new message
    track_actionable_message(channel_id, thread_ts, new_message_ts)
