"""Response posting with attachment transparency.

Provides post_response() helper that appends transparency footer
showing what attachments were used in responses.

Phase 34-07: Transparency UI integration.
"""
import logging
from typing import TYPE_CHECKING, Optional

from slack_sdk.web.async_client import AsyncWebClient

if TYPE_CHECKING:
    from src.documents.retriever import AttachmentContext

logger = logging.getLogger(__name__)


async def post_response(
    client: AsyncWebClient,
    channel_id: str,
    thread_ts: Optional[str],
    text: str,
    blocks: Optional[list[dict]] = None,
    attachment_context: Optional["AttachmentContext"] = None,
) -> dict:
    """Post bot response with transparency footer.

    Adds attachment usage info to response when context is provided.

    Footer shows:
    - Used: filename (sections: X, Y)
    - [Show sources] [Stop using this file] buttons

    Args:
        client: Slack async client.
        channel_id: Channel to post to.
        thread_ts: Thread timestamp (or None for channel root).
        text: Message text (required fallback).
        blocks: Block Kit blocks for the message.
        attachment_context: AttachmentContext from retriever.

    Returns:
        Slack API response dict.
    """
    from src.slack.blocks.attachments import (
        build_used_attachments_footer,
        build_offer_attachments_block,
    )

    final_blocks = list(blocks) if blocks else []

    # Add attachment transparency footer
    if attachment_context:
        # Add "used" footer if content was included
        footer = build_used_attachments_footer(attachment_context)
        if footer:
            final_blocks.extend(footer)
            logger.debug(
                "Added attachment transparency footer",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "pinned_count": len(attachment_context.pinned),
                    "retrieved_count": len(attachment_context.retrieved_chunks),
                }
            )

        # Or add "offer" block if in CHAT mode (attachments available but not used)
        offer = build_offer_attachments_block(attachment_context)
        if offer:
            final_blocks.append(offer)
            logger.debug(
                "Added attachment offer block",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "available_count": len(attachment_context.offer_available),
                }
            )

    return await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=text,
        blocks=final_blocks if final_blocks else None,
    )


def post_response_sync(
    client,
    channel_id: str,
    thread_ts: Optional[str],
    text: str,
    blocks: Optional[list[dict]] = None,
    attachment_context: Optional["AttachmentContext"] = None,
) -> dict:
    """Synchronous version of post_response for Bolt handlers.

    Same transparency footer behavior but using sync WebClient.

    Args:
        client: Slack sync WebClient.
        channel_id: Channel to post to.
        thread_ts: Thread timestamp (or None for channel root).
        text: Message text (required fallback).
        blocks: Block Kit blocks for the message.
        attachment_context: AttachmentContext from retriever.

    Returns:
        Slack API response dict.
    """
    from src.slack.blocks.attachments import (
        build_used_attachments_footer,
        build_offer_attachments_block,
    )

    final_blocks = list(blocks) if blocks else []

    # Add attachment transparency footer
    if attachment_context:
        # Add "used" footer if content was included
        footer = build_used_attachments_footer(attachment_context)
        if footer:
            final_blocks.extend(footer)

        # Or add "offer" block if in CHAT mode
        offer = build_offer_attachments_block(attachment_context)
        if offer:
            final_blocks.append(offer)

    return client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=text,
        blocks=final_blocks if final_blocks else None,
    )
