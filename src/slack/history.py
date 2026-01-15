"""Conversation history fetching service for Slack channels and threads.

Provides reusable functions to fetch recent channel messages and thread replies
using Slack API. This is the foundation for context injection.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


def fetch_channel_history(
    client: WebClient,
    channel_id: str,
    before_ts: str | None = None,
    limit: int = 20
) -> list[dict]:
    """Fetch recent messages from a Slack channel.

    Args:
        client: Slack WebClient instance
        channel_id: The channel to fetch messages from
        before_ts: Optional timestamp - fetch messages before this time
        limit: Maximum number of messages to fetch (default: 20)

    Returns:
        List of message dicts from the Slack API response.
        Returns empty list on error (graceful degradation).

    Note:
        - Messages are returned in reverse chronological order (newest first)
        - Rate limits: Tier 3 for internal apps (~50 req/min)
    """
    try:
        kwargs = {
            "channel": channel_id,
            "limit": limit,
        }
        if before_ts:
            kwargs["latest"] = before_ts
            kwargs["inclusive"] = False

        result = client.conversations_history(**kwargs)
        messages = result.get("messages", [])
        logger.debug(
            f"Fetched {len(messages)} channel messages",
            extra={
                "channel_id": channel_id,
                "limit": limit,
                "before_ts": before_ts,
            }
        )
        return messages

    except SlackApiError as e:
        error_code = e.response.get("error", "unknown")
        if error_code == "ratelimited":
            retry_after = e.response.headers.get("Retry-After", "unknown")
            logger.warning(
                f"Rate limited fetching channel history, retry after {retry_after}s",
                extra={"channel_id": channel_id, "retry_after": retry_after}
            )
        else:
            logger.error(
                f"Slack API error fetching channel history: {error_code}",
                extra={"channel_id": channel_id, "error": error_code}
            )
        return []

    except Exception as e:
        logger.error(
            f"Unexpected error fetching channel history: {e}",
            extra={"channel_id": channel_id},
            exc_info=True
        )
        return []


def fetch_thread_history(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
) -> list[dict]:
    """Fetch all messages in a Slack thread.

    Args:
        client: Slack WebClient instance
        channel_id: The channel containing the thread
        thread_ts: The timestamp of the thread's root message

    Returns:
        List of message dicts from the Slack API response.
        Returns empty list on error (graceful degradation).

    Note:
        - Includes the root message as the first item
        - Returns up to 200 messages (threads are typically compact)
        - Messages are in chronological order (oldest first)
    """
    try:
        result = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=200,  # Threads are typically compact
        )
        messages = result.get("messages", [])
        logger.debug(
            f"Fetched {len(messages)} thread messages",
            extra={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
            }
        )
        return messages

    except SlackApiError as e:
        error_code = e.response.get("error", "unknown")
        if error_code == "ratelimited":
            retry_after = e.response.headers.get("Retry-After", "unknown")
            logger.warning(
                f"Rate limited fetching thread history, retry after {retry_after}s",
                extra={"channel_id": channel_id, "thread_ts": thread_ts, "retry_after": retry_after}
            )
        else:
            logger.error(
                f"Slack API error fetching thread history: {error_code}",
                extra={"channel_id": channel_id, "thread_ts": thread_ts, "error": error_code}
            )
        return []

    except Exception as e:
        logger.error(
            f"Unexpected error fetching thread history: {e}",
            extra={"channel_id": channel_id, "thread_ts": thread_ts},
            exc_info=True
        )
        return []


def format_messages_for_context(
    messages: list[dict],
    include_timestamps: bool = False
) -> str:
    """Format Slack messages for LLM context injection.

    Converts a list of Slack message dicts into a human-readable format
    suitable for including in prompts.

    Args:
        messages: List of Slack message dicts
        include_timestamps: Whether to include timestamps in output

    Returns:
        Formatted string with one message per line.
        Format: "[user] message" or "[user at ts] message" if include_timestamps

    Example:
        >>> messages = [{"user": "U123", "text": "Hello"}, {"user": "U456", "text": "Hi!"}]
        >>> format_messages_for_context(messages)
        '[U123] Hello\\n[U456] Hi!'
    """
    lines = []
    for msg in messages:
        user = msg.get("user", "unknown")
        text = msg.get("text", "")

        # Skip empty messages
        if not text:
            continue

        if include_timestamps:
            ts = msg.get("ts", "")
            lines.append(f"[{user} at {ts}] {text}")
        else:
            lines.append(f"[{user}] {text}")

    return "\n".join(lines)


@dataclass
class ConversationContext:
    """Two-layer conversation context for LLM prompts.

    Maintains both raw messages (bounded, recent) and a compressed summary
    (older context). This pattern reduces token costs by 80-90% while
    improving response quality through the combination of precision
    (raw messages) and compression (summary).

    Attributes:
        messages: Raw Slack messages (bounded, typically 10-30)
        summary: Compressed narrative of older conversation (None until summarized)
        last_updated_at: When context was last updated

    Example:
        >>> ctx = ConversationContext(messages=[...])
        >>> ctx.summary = "Team discussed auth implementation..."
        >>> prompt_text = ctx.to_prompt_context()
    """
    messages: list[dict] = field(default_factory=list)
    summary: str | None = None
    last_updated_at: datetime | None = None

    def to_prompt_context(self) -> str:
        """Format for LLM prompt injection.

        Combines summary and recent messages into a structured context
        string suitable for including in prompts.

        Returns:
            Formatted string with optional summary section and recent messages.
            Empty string if no context available.
        """
        parts = []

        if self.summary:
            parts.append(f"## Conversation Summary\n{self.summary}")

        if self.messages:
            formatted = format_messages_for_context(self.messages)
            if formatted:
                parts.append(f"## Recent Messages\n{formatted}")

        return "\n\n".join(parts)
