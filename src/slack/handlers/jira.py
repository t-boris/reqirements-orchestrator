"""Slack handlers for Jira commit flow."""

import logging
from typing import Any

from slack_bolt.async_app import AsyncAck
from slack_sdk.web.async_client import AsyncWebClient

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

    # Extract entity info from action value
    action = body["actions"][0]
    entity_id = action.get("value", "")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")

    logger.info(f"Commit to Jira requested for entity {entity_id} by {user_id}")

    # TODO: In full implementation:
    # 1. Load entity from projection
    # 2. Get channel config for project_key
    # 3. Call CommitHandler.commit_work_item()
    # 4. Based on result:
    #    - SUCCESS: Update entity via ChannelAggregate.commit_work_item()
    #    - DUPLICATE_FOUND: Post duplicate selection message
    #    - ERROR: Post error message

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":hourglass: Checking for duplicates before creating Jira issue...",
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
    # Value format: "entity_id:jira_key"
    value = action.get("value", "")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")

    if ":" not in value:
        logger.error(f"Invalid duplicate selection value: {value}")
        return

    entity_id, jira_key = value.split(":", 1)

    logger.info(f"User {user_id} selected existing {jira_key} for entity {entity_id}")

    # TODO: In full implementation:
    # 1. Call CommitHandler.commit_with_existing()
    # 2. Update entity via ChannelAggregate.commit_work_item()
    # 3. Post confirmation

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":link: Linking to existing issue {jira_key}...",
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

    # TODO: In full implementation:
    # 1. Skip preflight check (user confirmed)
    # 2. Call JiraSyncService directly to create
    # 3. Update entity via ChannelAggregate.commit_work_item()
    # 4. Post confirmation

    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":rocket: Creating new Jira issue...",
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
