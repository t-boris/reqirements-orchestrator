"""Help command handlers: /maro help.

Provides interactive help with examples.
"""

import logging

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


async def handle_help_command(channel_id: str, client: WebClient):
    """Handle /maro help - show interactive help with example buttons."""
    from src.slack.onboarding import get_help_blocks

    try:
        blocks = get_help_blocks()

        client.chat_postMessage(
            channel=channel_id,
            text="What MARO can do",
            blocks=blocks,
        )
    except Exception as e:
        logger.error(f"Failed to show help: {e}", exc_info=True)
        # Fallback to simple text message
        try:
            client.chat_postMessage(
                channel=channel_id,
                text="MARO Help: Use `/maro enable` to enable listening, `/maro help` for full help.",
            )
        except Exception:
            logger.exception("Failed to post fallback help message")
