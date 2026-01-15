"""Rolling summary service for conversation context compression.

Provides LLM-powered summarization to compress older conversation messages
into a concise narrative, reducing token costs by 80-90% while maintaining
context quality for agent responses.

Usage:
    from src.slack.summarizer import update_rolling_summary, should_update_summary

    # Check if summary update needed
    if should_update_summary(buffer_size=35, threshold=30):
        # Update summary with older messages
        new_summary = await update_rolling_summary(llm, current_summary, messages_to_compress)
"""

import logging
from src.llm import UnifiedChatClient

logger = logging.getLogger(__name__)


SUMMARY_PROMPT = """You are maintaining a rolling summary of a Slack conversation.

Current summary:
{current_summary}

New messages since last update:
{new_messages}

Update the summary to incorporate the new messages. Keep it concise (2-3 paragraphs max).
Focus on: topics discussed, decisions made, open questions, key participants.

Updated summary:"""


async def update_rolling_summary(
    llm_client: UnifiedChatClient,
    current_summary: str | None,
    new_messages: list[dict],
) -> str:
    """Update summary with new messages using LLM.

    Compresses a batch of messages into the rolling summary, preserving
    key context while reducing token count significantly.

    Args:
        llm_client: UnifiedChatClient instance for LLM calls
        current_summary: Existing summary text, or None if first summary
        new_messages: List of Slack message dicts to incorporate

    Returns:
        Updated summary text (2-3 paragraphs)

    Example:
        >>> from src.llm import get_llm
        >>> llm = get_llm()
        >>> summary = await update_rolling_summary(llm, None, messages[:10])
        >>> # Later...
        >>> summary = await update_rolling_summary(llm, summary, messages[10:20])
    """
    from src.slack.history import format_messages_for_context

    if not new_messages:
        return current_summary or ""

    messages_text = format_messages_for_context(new_messages, include_timestamps=True)

    prompt = SUMMARY_PROMPT.format(
        current_summary=current_summary or "No previous summary.",
        new_messages=messages_text
    )

    try:
        response = await llm_client.chat(prompt)
        return response.strip()
    except Exception as e:
        logger.error(f"Failed to update rolling summary: {e}", exc_info=True)
        # Return existing summary on failure (graceful degradation)
        return current_summary or ""


def should_update_summary(
    buffer_size: int,
    threshold: int = 30
) -> bool:
    """Determine if summary should be updated based on buffer size.

    The rolling summary is updated when the message buffer exceeds the
    threshold. This balances cost (LLM calls) vs freshness (context quality).

    Args:
        buffer_size: Current number of messages in raw buffer
        threshold: Update when buffer exceeds this (default: 30)

    Returns:
        True if summary should be updated

    Note:
        From research: update every 5-10 messages for active channels,
        but we use 30 as threshold to keep 20 raw and compress 10+ older.
    """
    return buffer_size > threshold
