"""Handlers for change request button actions."""

import logging
from datetime import datetime, timezone

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async
from src.schemas.change_request import ChangeRequest, ChangeOperation
from src.slack.blocks.change_request import build_change_applied_blocks

logger = logging.getLogger(__name__)


def handle_change_request_approve(ack, body: dict, client: WebClient) -> None:
    """Handle Approve button click on change request preview."""
    ack()
    _run_async(_handle_change_request_approve_async(body, client))


async def _handle_change_request_approve_async(body: dict, client: WebClient) -> None:
    """Async handler for change request approval."""
    try:
        action = body["actions"][0]
        request_id = action.get("value", "")
        channel_id = body["channel"]["id"]
        thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
        user_id = body["user"]["id"]

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

    except Exception as e:
        logger.error(f"Error handling change request approve: {e}", exc_info=True)


def handle_change_request_cancel(ack, body: dict, client: WebClient) -> None:
    """Handle Cancel button click on change request preview."""
    ack()
    _run_async(_handle_change_request_cancel_async(body, client))


async def _handle_change_request_cancel_async(body: dict, client: WebClient) -> None:
    """Async handler for change request cancellation."""
    try:
        action = body["actions"][0]
        request_id = action.get("value", "")
        channel_id = body["channel"]["id"]
        thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
        user_id = body["user"]["id"]

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="_Change request cancelled._",
        )

        logger.info(f"Change request {request_id} cancelled by {user_id}")

    except Exception as e:
        logger.error(f"Error handling change request cancel: {e}", exc_info=True)


def handle_change_request_edit(ack, body: dict, client: WebClient) -> None:
    """Handle Edit button click on change request preview."""
    ack()
    _run_async(_handle_change_request_edit_async(body, client))


async def _handle_change_request_edit_async(body: dict, client: WebClient) -> None:
    """Async handler for change request edit."""
    try:
        action = body["actions"][0]
        request_id = action.get("value", "")
        channel_id = body["channel"]["id"]
        thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
        user_id = body["user"]["id"]

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Please describe the changes you'd like to make differently.",
        )

        logger.info(f"Change request {request_id} edit requested by {user_id}")

    except Exception as e:
        logger.error(f"Error handling change request edit: {e}", exc_info=True)
