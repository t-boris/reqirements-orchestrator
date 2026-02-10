"""Slack handlers for Jira commit flow."""

import logging
from typing import Any

from slack_bolt.async_app import AsyncAck
from slack_sdk.web.async_client import AsyncWebClient

from src.config import get_settings
from src.domain.entities import ApprovedEntity
from src.domain.types import EntityId, JiraKey, UserId
from src.infrastructure.aggregate_loader import load_aggregate, save_events
from src.jira.factory import get_sync_service
from src.jira.sync_service import DuplicateDetectedError, JiraSyncError

logger = logging.getLogger(__name__)


async def handle_commit_to_jira(
    ack: AsyncAck,
    body: dict[str, Any],
    client: AsyncWebClient,
) -> None:
    """Handle 'Commit to Jira' button click.

    Initiates commit flow for an approved entity.
    """
    await ack()

    action = body["actions"][0]
    entity_id = action.get("value", "")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    message_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts

    logger.info(f"Commit to Jira requested for entity {entity_id} by {user_id}")

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=":hourglass: Checking for duplicates before creating Jira issue...",
    )

    try:
        aggregate = await load_aggregate(channel_id)
        entity = aggregate.get_entity(EntityId(entity_id))

        if entity is None:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":x: Entity `{entity_id}` not found in this channel.",
            )
            return

        if not isinstance(entity, ApprovedEntity):
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":x: Entity must be approved before committing to Jira. Current state: {type(entity).__name__}",
            )
            return

        settings = get_settings()
        sync_service = get_sync_service()

        # Get channel-specific Jira project or fall back to default
        from src.infrastructure.channel_config import get_jira_project
        channel_project = await get_jira_project(channel_id)
        project_key = channel_project or settings.jira_default_project

        # Check if entity has a parent and if that parent has a Jira key
        epic_key = None
        if hasattr(entity.content, "parent_id") and entity.content.parent_id:
            parent = aggregate.get_entity(entity.content.parent_id)
            if parent and hasattr(parent, "jira_link") and parent.jira_link:
                epic_key = parent.jira_link.jira_key
                logger.info(f"Entity {entity_id} has parent with Jira key {epic_key}")

        jira_key = await sync_service.commit_work_item(entity, project_key, epic_key=epic_key)

        committed = aggregate.commit_work_item(
            entity_id=EntityId(entity_id),
            actor_id=UserId(user_id),
            jira_key=JiraKey(jira_key),
        )
        await save_events(aggregate)

        jira_url = f"{settings.jira_url}/browse/{jira_key}"
        title = entity.content.title

        # Get the entity's canonical (pinned) message timestamp
        pinned_message_ts = getattr(entity, 'canonical_message_ts', None)

        # Update the entity's pinned message with Jira link
        if pinned_message_ts:
            try:
                # Fetch the current pinned message to update it
                pinned_msg = await client.conversations_history(
                    channel=channel_id,
                    latest=pinned_message_ts,
                    limit=1,
                    inclusive=True,
                )
                if pinned_msg.get("messages"):
                    original_blocks = pinned_msg["messages"][0].get("blocks", [])
                    # Remove existing actions blocks and add Jira link
                    updated_blocks = [
                        block for block in original_blocks
                        if block.get("type") != "actions"
                    ]
                    updated_blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":link: *Jira:* <{jira_url}|{jira_key}>",
                        },
                    })
                    await client.chat_update(
                        channel=channel_id,
                        ts=pinned_message_ts,
                        blocks=updated_blocks,
                        text=f"{title} — {jira_key}",
                    )
            except Exception as update_err:
                logger.warning(f"Failed to update pinned message: {update_err}")

            # Post commit notification as thread reply to pinned message
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=pinned_message_ts,
                text=f":rocket: Committed to Jira by <@{user_id}> — <{jira_url}|{jira_key}>",
            )
        else:
            # Fallback: post to channel if no pinned message (shouldn't happen)
            logger.warning(f"Entity {entity_id} has no canonical_message_ts")
            await client.chat_postMessage(
                channel=channel_id,
                text=f":rocket: *{title}* committed to Jira: <{jira_url}|{jira_key}>",
            )

        # Also update the button-click message if different from pinned
        if message_ts and message_ts != pinned_message_ts:
            original_blocks = body.get("message", {}).get("blocks", [])
            updated_blocks = [
                block for block in original_blocks
                if block.get("type") != "actions"
            ]
            updated_blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":white_check_mark: Committed to Jira: <{jira_url}|{jira_key}>",
                },
            })
            await client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=updated_blocks,
                text=f"{title} committed to Jira: {jira_key}",
            )

    except DuplicateDetectedError as e:
        blocks = build_duplicate_selection_blocks(
            entity_id=entity_id,
            duplicate_keys=e.duplicate_keys,
            original_title=getattr(entity.content, "title", entity_id),
        )
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Potential duplicates found: {', '.join(e.duplicate_keys)}",
            blocks=blocks,
        )

    except JiraSyncError as e:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":x: Failed to commit to Jira: {e}",
        )

    except Exception as e:
        logger.error(f"Error committing to Jira: {e}", exc_info=True)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=":x: An unexpected error occurred while committing to Jira.",
        )


async def handle_select_duplicate(
    ack: AsyncAck,
    body: dict[str, Any],
    client: AsyncWebClient,
) -> None:
    """Handle duplicate selection from user.

    User chose to link to an existing Jira issue.
    """
    await ack()

    action = body["actions"][0]
    value = action.get("value", "")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")

    if ":" not in value:
        logger.error(f"Invalid duplicate selection value: {value}")
        return

    entity_id, jira_key = value.split(":", 1)

    logger.info(f"User {user_id} selected existing {jira_key} for entity {entity_id}")

    try:
        aggregate = await load_aggregate(channel_id)
        entity = aggregate.get_entity(EntityId(entity_id))

        if entity is None or not isinstance(entity, ApprovedEntity):
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":x: Entity `{entity_id}` not found or not in approved state.",
            )
            return

        committed = aggregate.commit_work_item(
            entity_id=EntityId(entity_id),
            actor_id=UserId(user_id),
            jira_key=JiraKey(jira_key),
        )
        await save_events(aggregate)

        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":link: Linked entity to existing issue *{jira_key}*",
        )

    except Exception as e:
        logger.error(f"Error linking to duplicate: {e}", exc_info=True)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":x: Failed to link to {jira_key}: {e}",
        )


async def handle_create_anyway(
    ack: AsyncAck,
    body: dict[str, Any],
    client: AsyncWebClient,
) -> None:
    """Handle 'Create anyway' button when duplicates found.

    User explicitly chose to create new issue despite duplicates.
    """
    await ack()

    action = body["actions"][0]
    entity_id = action.get("value", "")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")

    logger.info(f"User {user_id} chose to create anyway for entity {entity_id}")

    try:
        aggregate = await load_aggregate(channel_id)
        entity = aggregate.get_entity(EntityId(entity_id))

        if entity is None or not isinstance(entity, ApprovedEntity):
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":x: Entity `{entity_id}` not found or not in approved state.",
            )
            return

        settings = get_settings()
        sync_service = get_sync_service()

        # Get channel-specific Jira project or fall back to default
        from src.infrastructure.channel_config import get_jira_project
        channel_project = await get_jira_project(channel_id)
        project_key = channel_project or settings.jira_default_project

        # Check if entity has a parent with Jira key
        epic_key = None
        if hasattr(entity.content, "parent_id") and entity.content.parent_id:
            parent = aggregate.get_entity(entity.content.parent_id)
            if parent and hasattr(parent, "jira_link") and parent.jira_link:
                epic_key = parent.jira_link.jira_key

        jira_key = await sync_service.jira.create_issue(
            project_key=project_key,
            summary=entity.content.title,
            issue_type=sync_service._map_issue_type(
                getattr(entity.content, "issue_type", "Task")
            ),
            description=getattr(entity.content, "description", ""),
            epic_key=epic_key,
        )

        committed = aggregate.commit_work_item(
            entity_id=EntityId(entity_id),
            actor_id=UserId(user_id),
            jira_key=JiraKey(jira_key),
        )
        await save_events(aggregate)

        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":rocket: Created new Jira issue *{jira_key}* (duplicates ignored)",
        )

    except Exception as e:
        logger.error(f"Error creating Jira issue: {e}", exc_info=True)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":x: Failed to create Jira issue: {e}",
        )


def build_duplicate_selection_blocks(
    entity_id: str,
    duplicate_keys: tuple[str, ...],
    original_title: str,
) -> list[dict[str, Any]]:
    """Build blocks for duplicate selection UI.

    Shows potential duplicates and lets user choose:
    - Link to existing
    - Create anyway
    """
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Potential duplicates found for:* {original_title}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Select an existing issue to link, or create a new one:",
            },
        },
    ]

    # Add button for each duplicate
    elements = []
    for jira_key in duplicate_keys[:5]:  # Limit to 5
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": jira_key},
            "action_id": f"select_duplicate_{jira_key}",
            "value": f"{entity_id}:{jira_key}",
        })

    # Add "Create anyway" button
    elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Create New"},
        "action_id": "create_anyway",
        "value": entity_id,
        "style": "primary",
    })

    blocks.append({
        "type": "actions",
        "elements": elements,
    })

    return blocks
