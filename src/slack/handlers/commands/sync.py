"""Sync command handlers: /maro sync.

Delegates to the main sync handler module for Jira synchronization.
"""

import logging

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


async def handle_sync_command(
    channel_id: str,
    client: WebClient,
    user_id: str,
    auto_mode: bool = False,
):
    """Handle /maro sync command - show and apply Jira sync changes.

    Args:
        channel_id: Slack channel ID
        client: Slack WebClient
        user_id: User who invoked command
        auto_mode: If True, applies obvious changes automatically
    """
    from src.slack.handlers.sync import handle_maro_sync

    await handle_maro_sync(channel_id, client, user_id, auto_mode)
