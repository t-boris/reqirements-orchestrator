"""Handlers for commit approval actions (Phase 23.3).

Handles Approve & Commit, Edit, and Not now button clicks from commit preview.
"""
import asyncio
import json
import logging
from typing import Any

from slack_bolt import Ack, Respond
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from src.db import get_connection
from src.db.commit_store import CommitStore
from src.db.models import CommitType
from src.slack.blocks.commit import build_commit_success_blocks
from src.slack.channel_work_board import ChannelWorkBoardManager

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run async coroutine in sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def register_commit_handlers(app: AsyncApp) -> None:
    """Register commit-related action handlers.

    Actions:
    - approve_commit: Create commit entry and update board
    - edit_commit: Open edit modal (stub for now)
    - dismiss_commit: Remove the preview message
    """

    @app.action("approve_commit")
    def handle_approve_commit(ack: Ack, body: dict, client: Any, respond: Respond):
        """Handle Approve & Commit button click."""
        ack()
        _run_async(_handle_approve_commit_async(body, client, respond))

    @app.action("edit_commit")
    def handle_edit_commit(ack: Ack, body: dict, respond: Respond):
        """Handle Edit button click."""
        ack()
        respond(
            text="Edit functionality coming soon. For now, dismiss and recreate.",
            response_type="ephemeral",
        )

    @app.action("dismiss_commit")
    def handle_dismiss_commit(ack: Ack, body: dict, respond: Respond):
        """Handle Not now button click."""
        ack()
        respond(
            text="Commit preview dismissed. The draft is still available.",
            response_type="ephemeral",
            delete_original=True,
        )


async def _handle_approve_commit_async(
    body: dict,
    client: AsyncWebClient,
    respond: Respond,
) -> None:
    """Async handler for approve_commit action."""
    try:
        # Extract action data
        action = body.get("actions", [{}])[0]
        value_str = action.get("value", "{}")

        try:
            data = json.loads(value_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse commit value: {value_str}")
            respond(text="Error: Invalid commit data", response_type="ephemeral")
            return

        # Extract fields
        commit_type_str = data.get("commit_type", "decision")
        summary = data.get("summary", "")
        channel_id = data.get("channel_id")
        thread_ts = data.get("thread_ts")
        user_id = data.get("user_id") or body.get("user", {}).get("id")
        workitem_id = data.get("workitem_id")

        if not channel_id or not summary:
            respond(text="Error: Missing channel or summary", response_type="ephemeral")
            return

        # Map string to CommitType enum
        try:
            commit_type = CommitType(commit_type_str)
        except ValueError:
            commit_type = CommitType.DECISION

        # Create commit entry
        async with get_connection() as conn:
            store = CommitStore(conn)
            await store.create_tables()

            entry = await store.create(
                channel_id=channel_id,
                commit_type=commit_type,
                summary=summary,
                user_id=user_id,
                workitem_id=workitem_id,
                thread_ts=thread_ts,
            )

            logger.info(
                "Commit created",
                extra={
                    "commit_id": entry.id,
                    "commit_type": commit_type.value,
                    "channel_id": channel_id,
                    "user_id": user_id,
                }
            )

            # Update the channel work board
            board_manager = ChannelWorkBoardManager()
            await board_manager.post_or_update(client, channel_id, conn)

        # Replace preview with success message
        success_blocks = build_commit_success_blocks(
            commit_type=commit_type.value,
            summary=summary,
            committed_by=user_id,
            thread_ts=thread_ts,
            channel_id=channel_id,
        )

        respond(
            blocks=success_blocks,
            text=f"Committed: {summary}",
            replace_original=True,
        )

    except Exception as e:
        logger.error(f"Failed to handle approve_commit: {e}", exc_info=True)
        respond(
            text="Sorry, I couldn't process the commit. Please try again.",
            response_type="ephemeral",
        )
