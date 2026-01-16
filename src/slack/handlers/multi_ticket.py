"""Handlers for multi-ticket workflow.

Handles actions from multi-ticket preview:
- Quantity confirmation (>3 items)
- Split into batches
- Edit individual story
- Approve all
- Cancel
"""
import logging
from typing import Optional

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


def handle_multi_ticket_confirm_quantity(body: dict, client: WebClient) -> None:
    """Handle quantity confirmation (>3 items).

    When user confirms they want to create more than MULTI_TICKET_QUANTITY_THRESHOLD
    items, update state and continue to preview.

    Args:
        body: Slack action body
        client: Slack WebClient for API calls
    """
    channel = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")

    if not channel or not message_ts:
        logger.warning("Missing channel or message_ts in confirm_quantity body")
        return

    # Update message to show confirmation received
    client.chat_update(
        channel=channel,
        ts=message_ts,
        text="Quantity confirmed. Preparing preview...",
        blocks=[],
    )

    logger.info(
        "Multi-ticket quantity confirmed",
        extra={"channel": channel, "message_ts": message_ts},
    )

    # Note: State update + preview will be triggered by graph runner
    # This handler just updates the UI immediately


def handle_multi_ticket_split(body: dict, client: WebClient) -> None:
    """Handle split into batches request.

    When batch is too large, user can choose to split into smaller batches.
    Bot creates Epic first, then adds stories in groups.

    Args:
        body: Slack action body
        client: Slack WebClient for API calls
    """
    channel = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")

    if not channel or not message_ts:
        logger.warning("Missing channel or message_ts in split body")
        return

    client.chat_update(
        channel=channel,
        ts=message_ts,
        text="Splitting into batches. I'll create the Epic first, then add stories in groups.",
        blocks=[],
    )

    logger.info(
        "Multi-ticket split requested",
        extra={"channel": channel, "message_ts": message_ts},
    )

    # TODO: Implement batch splitting logic in graph runner
    # This will be wired up when the full multi-ticket flow is integrated


def handle_multi_ticket_edit_story(body: dict, client: WebClient) -> None:
    """Handle edit story button click.

    Opens modal to edit story title/description.

    Args:
        body: Slack action body
        client: Slack WebClient for API calls
    """
    trigger_id = body.get("trigger_id")
    if not trigger_id:
        logger.warning("Missing trigger_id in edit_story body")
        return

    story_id = _extract_story_id(body)
    ui_version = _extract_ui_version(body)

    logger.info(
        "Multi-ticket edit story requested",
        extra={"story_id": story_id, "ui_version": ui_version},
    )

    # TODO: Import and call modal opener when modals module exists
    # from src.slack.modals import open_story_edit_modal
    # open_story_edit_modal(client, trigger_id, story_id)

    # For now, log that the action was received
    logger.info(f"Would open story edit modal for story {story_id}")


def handle_multi_ticket_approve(body: dict, client: WebClient) -> None:
    """Handle approve all button click.

    Triggers batch creation in Jira.

    Args:
        body: Slack action body
        client: Slack WebClient for API calls
    """
    channel = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    user_id = body.get("user", {}).get("id")

    if not channel or not message_ts:
        logger.warning("Missing channel or message_ts in approve body")
        return

    # Check ui_version from action value for stale button detection
    ui_version = _extract_ui_version(body)

    logger.info(
        "Multi-ticket approve requested",
        extra={
            "channel": channel,
            "message_ts": message_ts,
            "user_id": user_id,
            "ui_version": ui_version,
        },
    )

    client.chat_update(
        channel=channel,
        ts=message_ts,
        text="Creating tickets in Jira...",
        blocks=[],
    )

    # Note: Actual batch creation will be triggered by graph runner
    # This handler updates UI to show progress


def handle_multi_ticket_cancel(body: dict, client: WebClient) -> None:
    """Handle cancel button click.

    Cancels multi-ticket creation and clears state.

    Args:
        body: Slack action body
        client: Slack WebClient for API calls
    """
    channel = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    user_id = body.get("user", {}).get("id")

    if not channel or not message_ts:
        logger.warning("Missing channel or message_ts in cancel body")
        return

    logger.info(
        "Multi-ticket creation cancelled",
        extra={
            "channel": channel,
            "message_ts": message_ts,
            "user_id": user_id,
        },
    )

    client.chat_update(
        channel=channel,
        ts=message_ts,
        text="Multi-ticket creation cancelled.",
        blocks=[],
    )


def _extract_story_id(body: dict) -> Optional[str]:
    """Extract story ID from action_id.

    Action ID format: multi_ticket_edit_story:{story_id}:{ui_version}

    Args:
        body: Slack action body

    Returns:
        Story ID or None if not found
    """
    actions = body.get("actions", [])
    if actions:
        action_id = actions[0].get("action_id", "")
        # Format: multi_ticket_edit_story:story_id:ui_version
        parts = action_id.split(":")
        if len(parts) >= 2:
            return parts[1]
    return None


def _extract_ui_version(body: dict) -> int:
    """Extract ui_version from action value or action_id.

    UI version is used for stale button detection. Format in action_id:
    {action_type}:{identifier}:{ui_version}

    Or in action value: {value}:{ui_version}

    Args:
        body: Slack action body

    Returns:
        UI version number (0 if not found)
    """
    actions = body.get("actions", [])
    if not actions:
        return 0

    action = actions[0]

    # Try action_id first (format: action_type:id:version)
    action_id = action.get("action_id", "")
    parts = action_id.split(":")
    if len(parts) >= 3 and parts[-1].isdigit():
        return int(parts[-1])

    # Try action value (format: value:version)
    value = action.get("value", "")
    if ":" in value:
        version_part = value.split(":")[-1]
        if version_part.isdigit():
            return int(version_part)

    return 0
