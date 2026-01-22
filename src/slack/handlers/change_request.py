"""Handlers for change request button actions."""

import logging
from datetime import datetime, timezone

from slack_sdk import WebClient

from src.schemas.change_request import ChangeRequest, ChangeOperation
from src.slack.blocks.change_request import build_change_applied_blocks

logger = logging.getLogger(__name__)


async def handle_change_request_approve(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    request_id: str,
) -> None:
    """Handle approval of a change request."""
    # Load change request from store
    # request = await change_request_store.get(request_id)

    # Apply changes to channel truth
    # await workitem_store.apply_changes(request.targets, request.changes)

    # Sync to Jira if needed
    jira_updated = False
    # if request.requires_jira_sync:
    #     await jira_service.apply_changes(request)
    #     jira_updated = True

    # Create commit entry
    # await commit_log.add(...)

    # Update message with confirmation
    # For now, just post confirmation
    blocks = build_change_applied_blocks(
        request=ChangeRequest(
            request_id=request_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            requester_id=user_id,
            operation=ChangeOperation.UPDATE,
            targets=[],
            changes=[],
            created_at=datetime.now(timezone.utc),
        ),
        jira_updated=jira_updated,
    )

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=blocks,
        text="Changes applied",
    )

    logger.info(f"Change request {request_id} approved by {user_id}")


async def handle_change_request_cancel(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    request_id: str,
) -> None:
    """Handle cancellation of a change request."""
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="_Change request cancelled._",
    )

    logger.info(f"Change request {request_id} cancelled by {user_id}")


async def handle_change_request_edit(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    request_id: str,
) -> None:
    """Handle edit request - prompt user for modifications."""
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="Please describe the changes you'd like to make differently.",
    )

    logger.info(f"Change request {request_id} edit requested by {user_id}")
