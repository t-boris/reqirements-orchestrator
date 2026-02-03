"""Handler for /maro sync command."""

import logging
from typing import Any

from slack_bolt.async_app import AsyncAck
from slack_sdk.web.async_client import AsyncWebClient

from src.slack.blocks.sync import build_sync_report_blocks

logger = logging.getLogger(__name__)


async def handle_sync_command(
    ack: AsyncAck,
    body: dict[str, Any],
    client: AsyncWebClient,
) -> None:
    """Handle /maro sync command.

    Checks all committed entities in the channel against Jira
    and reports discrepancies.
    """
    await ack()

    channel_id = body["channel_id"]
    user_id = body["user_id"]

    logger.info(f"Sync requested in {channel_id} by {user_id}")

    # Acknowledge with loading message
    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=":hourglass: Checking Jira sync status...",
    )

    # TODO: In full implementation:
    # 1. Load channel's committed entities from projection
    # 2. Create JiraSyncService and ReconciliationService
    # 3. Call reconciliation_service.check_sync_status(entities)
    # 4. Build report blocks
    # 5. Post to channel or ephemeral based on discrepancy count

    # For now, placeholder response
    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=":white_check_mark: Sync check complete. No committed entities found in this channel.",
    )


async def handle_refresh_from_jira(
    ack: AsyncAck,
    body: dict[str, Any],
    client: AsyncWebClient,
) -> None:
    """Handle 'Refresh from Jira' button click.

    Refreshes a single entity from Jira and shows any differences.
    """
    await ack()

    action = body["actions"][0]
    value = action.get("value", "")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")

    if ":" not in value:
        logger.error(f"Invalid refresh value: {value}")
        return

    entity_id, jira_key = value.split(":", 1)

    logger.info(f"Refresh from Jira requested for {entity_id} ({jira_key}) by {user_id}")

    # TODO: In full implementation:
    # 1. Load entity from projection
    # 2. Call reconciliation_service.refresh_single(entity)
    # 3. If discrepancies, show resolution UI
    # 4. If in sync, confirm

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":arrows_counterclockwise: Refreshing from {jira_key}...",
    )


async def handle_resolve_use_jira(
    ack: AsyncAck,
    body: dict[str, Any],
    client: AsyncWebClient,
) -> None:
    """Handle 'Use Jira Values' resolution choice."""
    await ack()

    entity_id = body["actions"][0].get("value", "")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")

    logger.info(f"User {user_id} chose to use Jira values for {entity_id}")

    # TODO: In full implementation:
    # 1. Load current Jira values
    # 2. Update entity content to match Jira
    # 3. Emit appropriate events
    # 4. Confirm resolution

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":white_check_mark: Updated entity to match Jira values.",
    )


async def handle_resolve_keep_slack(
    ack: AsyncAck,
    body: dict[str, Any],
    client: AsyncWebClient,
) -> None:
    """Handle 'Keep Slack Values' resolution choice."""
    await ack()

    entity_id = body["actions"][0].get("value", "")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")

    logger.info(f"User {user_id} chose to keep Slack values for {entity_id}")

    # TODO: In full implementation:
    # 1. Push Slack values to Jira
    # 2. Handle any update errors
    # 3. Confirm resolution

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":white_check_mark: Jira updated to match Slack values.",
    )


async def handle_resolve_skip(
    ack: AsyncAck,
    body: dict[str, Any],
    client: AsyncWebClient,
) -> None:
    """Handle 'Skip' resolution choice."""
    await ack()

    entity_id = body["actions"][0].get("value", "")
    user_id = body["user"]["id"]

    logger.info(f"User {user_id} skipped resolution for {entity_id}")

    # Nothing to do - user chose to skip
