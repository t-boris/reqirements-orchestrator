"""Attribution schema for multi-user support.

Tracks who said what with source references.
Enables "X proposed by @A (link)" formatting.
"""
from typing import Optional
from pydantic import BaseModel, Field


class MessageAttribution(BaseModel):
    """Attribution for a piece of content to its source message.

    Used to track who said what in drafts, constraints, decisions.
    Enables "X proposed by @A (link)" formatting.
    """

    author_user_id: str = Field(description="Slack user ID who wrote this")
    source_message_ts: str = Field(description="Slack message timestamp")
    source_permalink: Optional[str] = Field(
        default=None,
        description="Slack permalink to source message"
    )
    confidence: float = Field(
        default=1.0,
        description="Confidence score for extracted content (0.0-1.0)"
    )

    def format_reference(self, display_name: Optional[str] = None) -> str:
        """Format as 'by @user (link)' for display.

        Args:
            display_name: Optional display name to use instead of user ID mention

        Returns:
            Formatted reference string like "by @user (source)" or "by display_name (source)"
        """
        name = display_name or f"<@{self.author_user_id}>"
        if self.source_permalink:
            return f"by {name} (<{self.source_permalink}|source>)"
        return f"by {name}"


class AttributedContent(BaseModel):
    """Content with attribution metadata.

    Wraps any extracted content (constraint, decision, requirement)
    with its source attribution.
    """

    content: str = Field(description="The actual content/text")
    attribution: MessageAttribution = Field(description="Source attribution")
    content_type: str = Field(
        default="general",
        description="Type: constraint, decision, requirement, summary"
    )
