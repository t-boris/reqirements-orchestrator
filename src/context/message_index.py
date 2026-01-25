"""Message index with caching for rendered blocks."""
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Literal, Optional

from src.slack.block_renderer import render_blocks


@dataclass(frozen=True)
class NormalizedMessage:
    """Normalized message for LLM context.

    All messages have consistent structure regardless of source.
    """

    message_type: Literal["user", "bot", "system"]
    """Type: user message, bot response, or system event."""

    author: str
    """Author identifier: user_id for users, 'BOT' for bot."""

    text: str
    """Message text content."""

    rendered_text: str
    """Rendered text including block content. Same as text for users."""

    ts: str
    """Slack message timestamp."""

    edited_ts: Optional[str] = None
    """Edit timestamp if message was edited."""

    def to_context_line(self) -> str:
        """Format for context injection.

        Format: [author]: rendered_text
        """
        content = self.rendered_text or self.text
        if self.message_type == "bot":
            return f"[MARO]: {content}"
        elif self.message_type == "system":
            return f"[System]: {content}"
        else:
            return f"[{self.author}]: {content}"

    @property
    def cache_key(self) -> str:
        """Cache key for this message version."""
        return f"{self.ts}:{self.edited_ts or '0'}"


class MessageIndex:
    """Cache and index for normalized messages.

    Avoids re-rendering blocks on every request.
    Uses LRU cache with configurable size.
    """

    def __init__(self, max_size: int = 1000):
        self._max_size = max_size
        self._cache: dict[str, NormalizedMessage] = {}
        self._bot_user_id: Optional[str] = None

    def set_bot_user_id(self, bot_user_id: str) -> None:
        """Set bot user ID for message type detection."""
        self._bot_user_id = bot_user_id

    def normalize(self, raw_message: dict) -> NormalizedMessage:
        """Normalize a raw Slack message.

        Args:
            raw_message: Raw message dict from Slack API.

        Returns:
            NormalizedMessage with rendered blocks.
        """
        ts = raw_message.get("ts", "")
        edited_ts = raw_message.get("edited", {}).get("ts")
        cache_key = f"{ts}:{edited_ts or '0'}"

        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Determine message type
        user = raw_message.get("user", "")
        bot_id = raw_message.get("bot_id")
        subtype = raw_message.get("subtype", "")

        if bot_id or subtype == "bot_message" or user == self._bot_user_id:
            message_type = "bot"
            author = "BOT"
        elif subtype in ("channel_join", "channel_leave", "channel_topic"):
            message_type = "system"
            author = "SYSTEM"
        else:
            message_type = "user"
            author = user

        # Get text and render blocks
        text = raw_message.get("text", "")
        blocks = raw_message.get("blocks", [])

        if blocks and message_type == "bot":
            # Bot messages with blocks: render blocks
            rendered = render_blocks(blocks)
            # Combine text and rendered blocks if both exist
            if text and rendered:
                rendered_text = f"{text}\n{rendered}"
            elif rendered:
                rendered_text = rendered
            else:
                rendered_text = text
        else:
            # User messages or no blocks: use text as-is
            rendered_text = text

        # Create normalized message
        normalized = NormalizedMessage(
            message_type=message_type,
            author=author,
            text=text,
            rendered_text=rendered_text,
            ts=ts,
            edited_ts=edited_ts,
        )

        # Cache with eviction
        self._cache[cache_key] = normalized
        self._evict_if_needed()

        return normalized

    def normalize_batch(self, messages: list[dict]) -> list[NormalizedMessage]:
        """Normalize a batch of messages.

        Args:
            messages: List of raw Slack messages.

        Returns:
            List of NormalizedMessages in same order.
        """
        return [self.normalize(msg) for msg in messages]

    def _evict_if_needed(self) -> None:
        """Evict oldest entries if cache exceeds max size."""
        while len(self._cache) > self._max_size:
            # Remove first (oldest) entry
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()

    @property
    def size(self) -> int:
        """Current cache size."""
        return len(self._cache)


# Module-level singleton for convenience
_index = MessageIndex()


def get_message_index() -> MessageIndex:
    """Get the singleton MessageIndex instance."""
    return _index


def normalize_message(raw_message: dict) -> NormalizedMessage:
    """Convenience function to normalize a single message."""
    return _index.normalize(raw_message)
