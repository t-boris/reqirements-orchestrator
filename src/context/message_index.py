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
