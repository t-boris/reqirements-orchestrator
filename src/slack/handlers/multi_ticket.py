"""Handlers for multi-ticket workflow.

Handles actions from multi-ticket preview:
- Quantity confirmation (>3 items)
- Split into batches
- Edit individual item (epic/story)
- Edit submit and preview refresh
- Remove item
- Approve all
- Cancel
"""
import json
import logging
from typing import Optional

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async
from src.graph.runner import get_runner
from src.slack.session import SessionIdentity

logger = logging.getLogger(__name__)


def handle_multi_ticket_confirm_quantity(ack, body: dict, client: WebClient) -> None:
    """Handle quantity confirmation (>3 items).

    When user confirms they want to create more than MULTI_TICKET_QUANTITY_THRESHOLD
    items, update state and continue to preview.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_confirm_quantity_async(body, client))


async def _handle_multi_ticket_confirm_quantity_async(body: dict, client: WebClient) -> None:
    """Async handler for multi-ticket quantity confirmation."""
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


def handle_multi_ticket_split(ack, body: dict, client: WebClient) -> None:
    """Handle split into batches request.

    When batch is too large, user can choose to split into smaller batches.
    Bot creates Epic first, then adds stories in groups.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_split_async(body, client))


async def _handle_multi_ticket_split_async(body: dict, client: WebClient) -> None:
    """Async handler for multi-ticket split."""
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


def handle_multi_ticket_edit_item(ack, body: dict, client: WebClient) -> None:
    """Handle edit item button click.

    Opens modal to edit item (epic or story) with all fields.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_edit_item_async(body, client))


# Keep old name as alias for backward compatibility with existing router
handle_multi_ticket_edit_story = handle_multi_ticket_edit_item


async def _handle_multi_ticket_edit_item_async(body: dict, client: WebClient) -> None:
    """Async handler for multi-ticket edit item.

    1. Parse item_id from action_id
    2. Find item in state's multi_ticket_state.items
    3. Open modal with form fields
    """
    trigger_id = body.get("trigger_id")
    if not trigger_id:
        logger.warning("Missing trigger_id in edit_item body")
        return

    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts

    if not channel_id:
        logger.warning("Missing channel_id in edit_item body")
        return

    item_id = _extract_item_id(body)
    ui_version = _extract_ui_version(body)

    logger.info(
        "Multi-ticket edit item requested",
        extra={"item_id": item_id, "ui_version": ui_version, "channel_id": channel_id},
    )

    # Get state to find the item
    team_id = body.get("team", {}).get("id", "unknown")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for edit_item: {e}", exc_info=True)
        return

    multi_ticket_state = state.get("multi_ticket_state")
    if not multi_ticket_state:
        logger.warning("No multi_ticket_state found")
        return

    items = multi_ticket_state.get("items", [])
    item = None
    for i in items:
        if i.get("id") == item_id:
            item = i
            break

    if not item:
        logger.warning(f"Item {item_id} not found in multi_ticket_state")
        return

    # Build and open modal
    modal_view = _build_edit_item_modal(
        item=item,
        channel_id=channel_id,
        thread_ts=thread_ts,
        message_ts=message_ts,
    )

    try:
        client.views_open(
            trigger_id=trigger_id,
            view=modal_view,
        )
    except Exception as e:
        logger.error(f"Failed to open edit item modal: {e}", exc_info=True)


def handle_multi_ticket_approve(ack, body: dict, client: WebClient) -> None:
    """Handle approve all button click.

    Triggers batch creation in Jira.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_approve_async(body, client))


async def _handle_multi_ticket_approve_async(body: dict, client: WebClient) -> None:
    """Async handler for multi-ticket approve."""
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


def handle_multi_ticket_cancel(ack, body: dict, client: WebClient) -> None:
    """Handle cancel button click.

    Cancels multi-ticket creation and clears state.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_cancel_async(body, client))


async def _handle_multi_ticket_cancel_async(body: dict, client: WebClient) -> None:
    """Async handler for multi-ticket cancel."""
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


def _extract_item_id(body: dict) -> Optional[str]:
    """Extract item ID from action_id.

    Action ID format: multi_ticket_edit_item:{item_id}:{ui_version}
    or multi_ticket_remove_item:{item_id}:{ui_version}

    Args:
        body: Slack action body

    Returns:
        Item ID or None if not found
    """
    actions = body.get("actions", [])
    if actions:
        action_id = actions[0].get("action_id", "")
        # Format: multi_ticket_edit_item:item_id:ui_version
        parts = action_id.split(":")
        if len(parts) >= 2:
            return parts[1]
    return None


# Alias for backward compatibility
_extract_story_id = _extract_item_id


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


def _build_edit_item_modal(
    item: dict,
    channel_id: str,
    thread_ts: str,
    message_ts: Optional[str] = None,
) -> dict:
    """Build modal view for editing a multi-ticket item.

    Args:
        item: MultiTicketItem dict with id, type, title, description, etc.
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        message_ts: Preview message timestamp for updating after edit

    Returns:
        Slack modal view structure
    """
    item_id = item.get("id", "")
    item_type = item.get("type", "story")
    title = item.get("title", "")
    description = item.get("description", "")
    problem_statement = item.get("problem_statement", "")
    acceptance_criteria = item.get("acceptance_criteria", "")

    # Build private metadata for submission handler
    private_metadata = json.dumps({
        "item_id": item_id,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "message_ts": message_ts,
    })

    # Type selection: Epic or Story
    type_options = [
        {"text": {"type": "plain_text", "text": "Epic"}, "value": "epic"},
        {"text": {"type": "plain_text", "text": "Story"}, "value": "story"},
    ]

    # Find initial selected type
    initial_type = next(
        (opt for opt in type_options if opt["value"] == item_type),
        type_options[1],  # Default to story
    )

    modal: dict = {
        "type": "modal",
        "callback_id": "multi_ticket_edit_submit",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Edit Item"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            # Title input (required)
            {
                "type": "input",
                "block_id": "title_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "title",
                    "initial_value": title,
                    "placeholder": {"type": "plain_text", "text": "Enter title..."},
                },
                "label": {"type": "plain_text", "text": "Title"},
            },
            # Type selection (radio buttons)
            {
                "type": "input",
                "block_id": "type_block",
                "element": {
                    "type": "radio_buttons",
                    "action_id": "item_type",
                    "initial_option": initial_type,
                    "options": type_options,
                },
                "label": {"type": "plain_text", "text": "Type"},
            },
            # Description (multiline, required)
            {
                "type": "input",
                "block_id": "description_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "description",
                    "multiline": True,
                    "initial_value": description,
                    "placeholder": {"type": "plain_text", "text": "Enter description..."},
                },
                "label": {"type": "plain_text", "text": "Description"},
            },
            # Problem Statement (multiline, optional)
            {
                "type": "input",
                "block_id": "problem_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "problem_statement",
                    "multiline": True,
                    "initial_value": problem_statement,
                    "placeholder": {"type": "plain_text", "text": "What problem does this solve?"},
                },
                "label": {"type": "plain_text", "text": "Problem Statement"},
            },
            # Acceptance Criteria (multiline, optional)
            {
                "type": "input",
                "block_id": "acceptance_criteria_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "acceptance_criteria",
                    "multiline": True,
                    "initial_value": acceptance_criteria,
                    "placeholder": {"type": "plain_text", "text": "How do we know when this is done?"},
                },
                "label": {"type": "plain_text", "text": "Acceptance Criteria"},
            },
        ],
    }

    return modal


def handle_multi_ticket_edit_submit(ack, body, client: WebClient, view) -> None:
    """Handle edit item modal submission.

    Update item in state and refresh preview message.

    Args:
        ack: Slack ack function
        body: Slack view submission body
        client: Slack WebClient for API calls
        view: Slack view object with submitted values
    """
    ack()
    _run_async(_handle_multi_ticket_edit_submit_async(body, client, view))


async def _handle_multi_ticket_edit_submit_async(body, client: WebClient, view) -> None:
    """Update item in state and refresh preview.

    1. Parse form values from view["state"]["values"]
    2. Get item_id and message context from private_metadata
    3. Update item in multi_ticket_state.items
    4. Rebuild preview blocks with updated item
    5. Update the preview message using client.chat_update()
    """
    user_id = body.get("user", {}).get("id")
    view_state = view.get("state", {}).get("values", {})
    private_metadata_raw = view.get("private_metadata", "{}")

    # Parse private metadata
    try:
        private_metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse private_metadata: {private_metadata_raw}")
        return

    item_id = private_metadata.get("item_id", "")
    channel_id = private_metadata.get("channel_id", "")
    thread_ts = private_metadata.get("thread_ts", "")
    message_ts = private_metadata.get("message_ts", "")

    logger.info(
        "Processing multi-ticket edit submit",
        extra={
            "item_id": item_id,
            "channel_id": channel_id,
            "user_id": user_id,
        }
    )

    if not channel_id or not thread_ts:
        logger.error("Missing channel_id or thread_ts in private_metadata")
        return

    # Parse submitted values
    title = view_state.get("title_block", {}).get("title", {}).get("value", "")
    item_type = view_state.get("type_block", {}).get("item_type", {}).get("selected_option", {}).get("value", "story")
    description = view_state.get("description_block", {}).get("description", {}).get("value", "")
    problem_statement = view_state.get("problem_block", {}).get("problem_statement", {}).get("value") or ""
    acceptance_criteria = view_state.get("acceptance_criteria_block", {}).get("acceptance_criteria", {}).get("value") or ""

    # Get runner and current state
    team_id = body.get("team", {}).get("id", "unknown")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for edit submit: {e}", exc_info=True)
        return

    multi_ticket_state = state.get("multi_ticket_state")
    if not multi_ticket_state:
        logger.warning("No multi_ticket_state found during edit submit")
        return

    items = multi_ticket_state.get("items", [])

    # Find and update the item
    item_found = False
    for item in items:
        if item.get("id") == item_id:
            item["title"] = title
            item["type"] = item_type
            item["description"] = description
            item["problem_statement"] = problem_statement
            item["acceptance_criteria"] = acceptance_criteria
            item_found = True
            break

    if not item_found:
        logger.warning(f"Item {item_id} not found during edit submit")
        return

    # Update state with modified items
    multi_ticket_state["items"] = items
    ui_version = state.get("ui_version", 0) + 1

    await runner.update_state({
        "multi_ticket_state": multi_ticket_state,
        "ui_version": ui_version,
    })

    # Rebuild and update preview message
    from src.slack.blocks.multi_ticket import build_multi_ticket_preview_blocks

    # Get source context from review_artifact if available
    review_artifact = state.get("review_artifact", {})
    source_persona = review_artifact.get("persona", "")
    source_date = ""
    if review_artifact.get("frozen_at"):
        # Extract date from ISO timestamp
        frozen_at = review_artifact.get("frozen_at", "")
        if frozen_at:
            source_date = frozen_at.split("T")[0] if "T" in frozen_at else frozen_at

    preview_blocks = build_multi_ticket_preview_blocks(
        items=items,
        ui_version=ui_version,
        source_persona=source_persona,
        source_date=source_date,
    )

    # Update the preview message
    if message_ts:
        try:
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f"Create {len(items)} Jira Tickets",
                blocks=preview_blocks,
            )
            logger.info(
                "Preview updated after edit",
                extra={"item_id": item_id, "message_ts": message_ts},
            )
        except Exception as e:
            logger.error(f"Failed to update preview message: {e}", exc_info=True)
    else:
        logger.warning("No message_ts available to update preview")


def handle_multi_ticket_remove_item(ack, body: dict, client: WebClient) -> None:
    """Handle remove item button click.

    Remove item from state and refresh preview.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_remove_item_async(body, client))


async def _handle_multi_ticket_remove_item_async(body: dict, client: WebClient) -> None:
    """Remove item from state and refresh preview.

    1. Parse item_id from action_id
    2. Remove item from multi_ticket_state.items
    3. If item was Epic with child Stories, also remove children (or orphan them)
    4. Rebuild and update preview
    5. If only 1 item remains, show message asking about single-ticket flow
    """
    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts

    if not channel_id or not message_ts:
        logger.warning("Missing channel_id or message_ts in remove_item body")
        return

    item_id = _extract_item_id(body)
    ui_version = _extract_ui_version(body)

    logger.info(
        "Multi-ticket remove item requested",
        extra={"item_id": item_id, "channel_id": channel_id},
    )

    # Get runner and current state
    team_id = body.get("team", {}).get("id", "unknown")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for remove_item: {e}", exc_info=True)
        return

    multi_ticket_state = state.get("multi_ticket_state")
    if not multi_ticket_state:
        logger.warning("No multi_ticket_state found during remove")
        return

    items = multi_ticket_state.get("items", [])

    # Find the item to remove
    item_to_remove = None
    for item in items:
        if item.get("id") == item_id:
            item_to_remove = item
            break

    if not item_to_remove:
        logger.warning(f"Item {item_id} not found during remove")
        return

    # Track IDs to remove (item itself and potentially children)
    ids_to_remove = {item_id}

    # If removing an Epic, also remove its child Stories (or orphan them)
    # For now, we orphan them (clear parent_id) rather than delete
    if item_to_remove.get("type") == "epic":
        for item in items:
            if item.get("parent_id") == item_id:
                # Orphan the story by clearing parent_id
                item["parent_id"] = None
                logger.info(f"Orphaned story {item.get('id')} after epic removal")

    # Remove the item(s)
    updated_items = [item for item in items if item.get("id") not in ids_to_remove]

    # Update state
    multi_ticket_state["items"] = updated_items
    new_ui_version = state.get("ui_version", 0) + 1

    await runner.update_state({
        "multi_ticket_state": multi_ticket_state,
        "ui_version": new_ui_version,
    })

    # Handle edge case: only 1 item remains
    if len(updated_items) == 1:
        # Show message suggesting single-ticket flow
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Only 1 item remains. Would you like to switch to the single-ticket editing experience for more detailed editing?",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Only *1 item* remains:\n\n*{updated_items[0].get('title', 'Untitled')}*\n\nWould you like to switch to single-ticket editing for a richer editing experience?",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Switch to Single-Ticket"},
                            "action_id": "multi_ticket_switch_to_single",
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Keep Multi-Ticket View"},
                            "action_id": f"multi_ticket_keep_multi:{new_ui_version}",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Cancel"},
                            "action_id": "multi_ticket_cancel",
                            "style": "danger",
                        },
                    ],
                },
            ],
        )
        return

    # Handle edge case: no items remain
    if len(updated_items) == 0:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="All items removed. Multi-ticket creation cancelled.",
            blocks=[],
        )
        return

    # Rebuild and update preview with remaining items
    from src.slack.blocks.multi_ticket import build_multi_ticket_preview_blocks

    # Get source context from review_artifact if available
    review_artifact = state.get("review_artifact", {})
    source_persona = review_artifact.get("persona", "")
    source_date = ""
    if review_artifact.get("frozen_at"):
        frozen_at = review_artifact.get("frozen_at", "")
        if frozen_at:
            source_date = frozen_at.split("T")[0] if "T" in frozen_at else frozen_at

    preview_blocks = build_multi_ticket_preview_blocks(
        items=updated_items,
        ui_version=new_ui_version,
        source_persona=source_persona,
        source_date=source_date,
    )

    try:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f"Create {len(updated_items)} Jira Tickets",
            blocks=preview_blocks,
        )
        logger.info(
            "Preview updated after remove",
            extra={"removed_item_id": item_id, "remaining_count": len(updated_items)},
        )
    except Exception as e:
        logger.error(f"Failed to update preview after remove: {e}", exc_info=True)
