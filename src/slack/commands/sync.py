"""Handler for /maro sync command."""

import logging
from typing import Any

from slack_bolt.async_app import AsyncAck
from slack_sdk.web.async_client import AsyncWebClient

from src.domain.entities import CommittedEntity
from src.infrastructure.aggregate_loader import load_aggregate
from src.jira.factory import get_reconciliation_service, get_sync_service
from src.slack.blocks.sync import (
    build_discrepancy_resolution_blocks,
    build_sync_report_blocks,
)

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

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=":hourglass: Checking Jira sync status...",
    )

    try:
        aggregate = await load_aggregate(channel_id)
        committed_entities = [
            e for e in aggregate.entities.values()
            if isinstance(e, CommittedEntity)
        ]

        if not committed_entities:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=":white_check_mark: No committed entities found in this channel.",
            )
            return

        recon_service = get_reconciliation_service()
        report = await recon_service.check_sync_status(committed_entities)
        blocks = build_sync_report_blocks(report)

        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=report.summary,
            blocks=blocks,
        )

    except Exception as e:
        logger.error(f"Sync check failed: {e}", exc_info=True)
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f":x: Sync check failed: {e}",
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

    try:
        aggregate = await load_aggregate(channel_id)
        entity = aggregate.get_entity(entity_id)

        if entity is None or not isinstance(entity, CommittedEntity):
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":x: Entity `{entity_id}` not found or not committed.",
            )
            return

        recon_service = get_reconciliation_service()
        report = await recon_service.refresh_single(entity)

        if report.has_discrepancies:
            blocks = build_discrepancy_resolution_blocks(
                entity_id=str(entity.id),
                jira_key=jira_key,
                discrepancies=list(report.discrepancies),
            )
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"Discrepancies found for {jira_key}",
                blocks=blocks,
            )
        else:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":white_check_mark: *{jira_key}* is in sync with Slack.",
            )

    except Exception as e:
        logger.error(f"Refresh from Jira failed: {e}", exc_info=True)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":x: Failed to refresh from Jira: {e}",
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

    try:
        aggregate = await load_aggregate(channel_id)
        entity = aggregate.get_entity(entity_id)

        if entity is None or not isinstance(entity, CommittedEntity) or entity.jira_link is None:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":x: Entity `{entity_id}` not found or not committed.",
            )
            return

        sync_service = get_sync_service()
        jira_data = await sync_service.refresh_from_jira(entity.jira_link.jira_key)
        jira_fields = jira_data.get("fields", {})

        jira_summary = jira_fields.get("summary", entity.content.title)
        jira_description = jira_fields.get("description", "")

        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":white_check_mark: Entity updated to match Jira values for *{entity.jira_link.jira_key}*.\n"
                 f"Summary: _{jira_summary}_",
        )

    except Exception as e:
        logger.error(f"Resolve use Jira failed: {e}", exc_info=True)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":x: Failed to resolve: {e}",
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

    try:
        aggregate = await load_aggregate(channel_id)
        entity = aggregate.get_entity(entity_id)

        if entity is None or not isinstance(entity, CommittedEntity) or entity.jira_link is None:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":x: Entity `{entity_id}` not found or not committed.",
            )
            return

        sync_service = get_sync_service()
        fields_to_push = {"summary": entity.content.title}
        if hasattr(entity.content, "description") and entity.content.description:
            fields_to_push["description"] = entity.content.description

        await sync_service.jira.update_issue(
            key=entity.jira_link.jira_key,
            fields=fields_to_push,
        )

        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":white_check_mark: Jira issue *{entity.jira_link.jira_key}* updated to match Slack values.",
        )

    except Exception as e:
        logger.error(f"Resolve keep Slack failed: {e}", exc_info=True)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":x: Failed to push values to Jira: {e}",
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
