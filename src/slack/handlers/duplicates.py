"""Duplicate ticket handling - link, create anyway, show more.

Handles all actions related to duplicate ticket detection and resolution.
"""

import json
import logging

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner
from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def handle_link_duplicate(ack, body, client: WebClient, action):
    """Synchronous wrapper for link duplicate action.

    Bolt calls handlers from a sync context. This wraps the async handler.
    """
    ack()
    _run_async(_handle_link_duplicate_async(body, client, action))


async def _handle_link_duplicate_async(body, client: WebClient, action):
    """Handle 'Link to this' button click on duplicate display.

    Binds the thread to the selected existing ticket.

    Flow:
    1. Parse button value: session_id:draft_hash:issue_key
    2. Store thread binding
    3. Update preview message to confirmation state
    4. Post confirmation message
    """
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    message_ts = body["message"]["ts"]  # Preview message to update
    user_id = body["user"]["id"]

    # Parse button value: session_id:draft_hash:issue_key
    button_value = action.get("value", "")
    parts = button_value.split(":")

    if len(parts) < 3:
        logger.error(f"Invalid link_duplicate button value: {button_value}")
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Error: Could not process link action. Please try again.",
        )
        return

    # Last part is issue_key, everything before that is session_id:draft_hash
    issue_key = parts[-1]
    # session_id might contain colons (team:channel:thread)
    draft_hash = parts[-2] if len(parts) > 3 else ""

    logger.info(
        "Linking thread to existing ticket",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "issue_key": issue_key,
            "user_id": user_id,
        }
    )

    # Store thread binding
    from src.slack.thread_bindings import get_binding_store

    binding_store = get_binding_store()
    await binding_store.bind(
        channel_id=channel,
        thread_ts=thread_ts,
        issue_key=issue_key,
        bound_by=user_id,
    )

    # Get issue URL from Jira
    from src.config.settings import get_settings

    settings = get_settings()
    issue_url = f"{settings.jira_url.rstrip('/')}/browse/{issue_key}"

    # Update preview message to linked confirmation state
    from src.slack.blocks import build_linked_confirmation_blocks

    confirmation_blocks = build_linked_confirmation_blocks(issue_key, issue_url)

    try:
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text=f"Linked to {issue_key}",
            blocks=confirmation_blocks,
        )
    except Exception as e:
        logger.warning(f"Failed to update preview message: {e}")

    # Post confirmation message in thread
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Linked to <{issue_url}|{issue_key}>. I'll keep you posted on updates.",
    )


def handle_create_anyway(ack, body, client: WebClient, action):
    """Synchronous wrapper for create anyway action.

    Bolt calls handlers from a sync context. This wraps the async handler.
    """
    ack()
    _run_async(_handle_create_anyway_async(body, client, action))


async def _handle_create_anyway_async(body, client: WebClient, action):
    """Handle 'Create new' button click when duplicates are shown.

    User chose to create a new ticket despite potential duplicates.
    Delegates to the existing approval flow.

    Flow:
    1. Parse button value: session_id:draft_hash
    2. Post the standard approval preview (replaces duplicate view)
    3. User can then approve or request changes
    """
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    message_ts = body["message"]["ts"]  # Preview message to update
    team_id = body["team"]["id"]
    user_id = body["user"]["id"]

    # Parse button value: session_id:draft_hash
    button_value = action.get("value", "")

    if ":" in button_value:
        # Handle session_id containing colons (team:channel:thread:hash)
        parts = button_value.rsplit(":", 1)
        session_id = parts[0]
        draft_hash = parts[1] if len(parts) > 1 else ""
    else:
        session_id = button_value
        draft_hash = ""

    logger.info(
        "User chose to create new ticket despite duplicates",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "user_id": user_id,
        }
    )

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Get current draft
    runner = get_runner(identity)
    state = await runner._get_current_state()
    draft = state.get("draft")

    if not draft:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Error: Could not find draft. Please start a new session.",
        )
        return

    # Compute current hash
    from src.skills.preview_ticket import compute_draft_hash
    from src.slack.blocks import build_draft_preview_blocks_with_hash

    current_hash = compute_draft_hash(draft)

    # Build standard approval preview (without duplicates, with approval buttons)
    preview_blocks = build_draft_preview_blocks_with_hash(
        draft=draft,
        session_id=session_id,
        draft_hash=current_hash,
        evidence_permalinks=None,
        potential_duplicates=None,  # Don't show duplicates again
        validator_findings=state.get("validation_report"),
    )

    # Update the message to show standard approval view
    try:
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text=f"Ticket preview for: {draft.title or 'Untitled'}",
            blocks=preview_blocks,
        )
    except Exception as e:
        logger.warning(f"Failed to update preview message: {e}")
        # Fall back to posting new message
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Ticket preview for: {draft.title or 'Untitled'}",
            blocks=preview_blocks,
        )


def handle_add_to_duplicate(ack, body, client: WebClient, action):
    """Synchronous wrapper for add to duplicate action.

    Bolt calls handlers from a sync context. This wraps the async handler.
    """
    ack()
    _run_async(_handle_add_to_duplicate_async(body, client, action))


async def _handle_add_to_duplicate_async(body, client: WebClient, action):
    """Handle 'Add as info' button click on duplicate display.

    Stub implementation for MVP - full functionality in Phase 11.3.
    Posts message explaining this feature will be available soon.
    """
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    user_id = body["user"]["id"]

    # Parse button value: session_id:draft_hash:issue_key
    button_value = action.get("value", "")
    parts = button_value.split(":")

    # Last part is issue_key
    issue_key = parts[-1] if parts else "the ticket"

    logger.info(
        "Add to duplicate requested (stub)",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "issue_key": issue_key,
            "user_id": user_id,
        }
    )

    # Post stub message
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Adding info to existing tickets will be available soon. "
             f"For now, you can *Link to {issue_key}* or *Create a new ticket*.",
    )


def handle_show_more_duplicates(ack, body, client: WebClient, action):
    """Synchronous wrapper for show more duplicates action.

    Opens a modal with all duplicate matches.
    Bolt calls handlers from a sync context. This wraps the async handler.
    """
    # Get trigger_id BEFORE ack (needed for modal)
    trigger_id = body.get("trigger_id")
    ack()
    _run_async(_handle_show_more_duplicates_async(body, client, action, trigger_id))


async def _handle_show_more_duplicates_async(body, client: WebClient, action, trigger_id):
    """Handle 'Show more' button click on duplicate display.

    Opens modal with all duplicate matches.
    """
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    team_id = body["team"]["id"]
    user_id = body["user"]["id"]

    # Parse button value: session_id:draft_hash
    button_value = action.get("value", "")

    if ":" in button_value:
        parts = button_value.rsplit(":", 1)
        session_id = parts[0]
        draft_hash = parts[1] if len(parts) > 1 else ""
    else:
        session_id = button_value
        draft_hash = ""

    logger.info(
        "Opening show more duplicates modal",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "user_id": user_id,
        }
    )

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Get current state to retrieve duplicates
    runner = get_runner(identity)
    state = await runner._get_current_state()
    decision_result = state.get("decision_result", {})
    potential_duplicates = decision_result.get("potential_duplicates", [])

    if not potential_duplicates:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No similar tickets found.",
        )
        return

    # Build and open modal
    from src.slack.modals import build_duplicate_modal

    modal_view = build_duplicate_modal(
        duplicates=potential_duplicates,
        session_id=session_id,
        draft_hash=draft_hash,
    )

    try:
        client.views_open(
            trigger_id=trigger_id,
            view=modal_view,
        )
    except Exception as e:
        logger.error(f"Failed to open duplicate modal: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Sorry, I couldn't open the similar tickets view. Please try again.",
        )


def handle_modal_link_duplicate(ack, body, client: WebClient, action):
    """Handle link button click from within the duplicate modal.

    Closes modal, links thread to ticket, updates original message.
    """
    ack(response_action="clear")  # Close modal
    _run_async(_handle_modal_link_duplicate_async(body, client, action))


async def _handle_modal_link_duplicate_async(body, client: WebClient, action):
    """Async handler for modal link duplicate action."""
    user_id = body["user"]["id"]
    private_metadata_raw = body["view"].get("private_metadata", "{}")

    # Parse private metadata
    try:
        private_metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse private_metadata: {private_metadata_raw}")
        return

    session_id = private_metadata.get("session_id", "")

    # Parse button value: session_id:draft_hash:issue_key
    button_value = action.get("value", "")
    parts = button_value.split(":")
    issue_key = parts[-1] if parts else ""

    # Parse session_id to get channel and thread
    # Format: team:channel:thread_ts
    session_parts = session_id.split(":")
    if len(session_parts) != 3:
        logger.error(f"Invalid session_id format: {session_id}")
        return

    team_id, channel, thread_ts = session_parts

    logger.info(
        "Linking from modal",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "issue_key": issue_key,
            "user_id": user_id,
        }
    )

    # Store thread binding
    from src.slack.thread_bindings import get_binding_store

    binding_store = get_binding_store()
    await binding_store.bind(
        channel_id=channel,
        thread_ts=thread_ts,
        issue_key=issue_key,
        bound_by=user_id,
    )

    # Get issue URL
    from src.config.settings import get_settings

    settings = get_settings()
    issue_url = f"{settings.jira_url.rstrip('/')}/browse/{issue_key}"

    # Post confirmation in thread
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Linked to <{issue_url}|{issue_key}>. I'll keep you posted on updates.",
    )


def handle_modal_create_anyway(ack, body, client: WebClient, action):
    """Handle create anyway button click from within the duplicate modal.

    Closes modal and proceeds with ticket creation.
    """
    ack(response_action="clear")  # Close modal
    _run_async(_handle_modal_create_anyway_async(body, client, action))


async def _handle_modal_create_anyway_async(body, client: WebClient, action):
    """Async handler for modal create anyway action."""
    user_id = body["user"]["id"]
    private_metadata_raw = body["view"].get("private_metadata", "{}")

    # Parse private metadata
    try:
        private_metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse private_metadata: {private_metadata_raw}")
        return

    session_id = private_metadata.get("session_id", "")
    draft_hash = private_metadata.get("draft_hash", "")

    # Parse session_id to get identity
    session_parts = session_id.split(":")
    if len(session_parts) != 3:
        logger.error(f"Invalid session_id format: {session_id}")
        return

    team_id, channel, thread_ts = session_parts

    logger.info(
        "Creating new ticket from modal",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "user_id": user_id,
        }
    )

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Get current draft
    runner = get_runner(identity)
    state = await runner._get_current_state()
    draft = state.get("draft")

    if not draft:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Error: Could not find draft. Please start a new session.",
        )
        return

    # Post standard approval preview
    from src.skills.preview_ticket import compute_draft_hash
    from src.slack.blocks import build_draft_preview_blocks_with_hash

    current_hash = compute_draft_hash(draft)

    preview_blocks = build_draft_preview_blocks_with_hash(
        draft=draft,
        session_id=session_id,
        draft_hash=current_hash,
        evidence_permalinks=None,
        potential_duplicates=None,
        validator_findings=state.get("validation_report"),
    )

    # Post new preview message (since we can't update from modal)
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Ticket preview for: {draft.title or 'Untitled'}",
        blocks=preview_blocks,
    )


async def handle_merge_context(ack, body, client, action):
    """Handle 'Merge context' button click.

    Links the related thread in session card and Epic summary.
    """
    ack()

    similar_session_id = action.get("value")
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]

    logger.info(
        f"Merge context requested",
        extra={
            "current_thread": thread_ts,
            "similar_session": similar_session_id,
        }
    )

    # Acknowledge the merge
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Context linked from related thread. I'll consider both discussions when gathering requirements.",
    )

    # TODO: Update session card with linked thread reference
    # TODO: Update Epic summary with cross-reference


async def handle_ignore_dedup(ack, body, client):
    """Handle 'Ignore' button click on dedup suggestion."""
    ack()

    # Just acknowledge - user chose to continue independently
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]

    # Delete the suggestion message
    message_ts = body["message"]["ts"]
    try:
        client.chat_delete(channel=channel, ts=message_ts)
    except Exception:
        pass  # May not have permission to delete
