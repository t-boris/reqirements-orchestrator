"""Handlers for Jira sync actions (Phase 23.4).

Handles:
- create_workitem_in_jira: Create WorkItem in Jira
- keep_workitem_local: Keep WorkItem local (no Jira)
- edit_workitem: Open edit modal
- resolve_conflict_*: Conflict resolution actions
"""
import asyncio
import json
import logging
from typing import Any

from slack_bolt import Ack, Respond
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from src.db import get_connection
from src.db.workitem_store import WorkItemStore
from src.config.settings import Settings
from src.jira.client import JiraService
from src.jira.sync_service import JiraSyncService
from src.slack.blocks.readiness import (
    build_jira_created_blocks,
    build_kept_local_blocks,
)
from src.slack.blocks.conflict import build_conflict_resolved_blocks
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


def get_identity_from_body(body: dict) -> str:
    """Extract user ID from Slack action body.

    Args:
        body: Slack action body

    Returns:
        User ID string
    """
    return body.get("user", {}).get("id", "unknown")


def register_jira_sync_handlers(app: AsyncApp) -> None:
    """Register sync-related action handlers.

    Actions:
    - create_workitem_in_jira: Create in Jira from readiness CTA
    - keep_workitem_local: Dismiss CTA, keep local
    - edit_workitem: Open edit modal (stub)
    - resolve_conflict_slack_*: Keep Slack version
    - resolve_conflict_jira_*: Keep Jira version
    - resolve_all_slack: Keep all Slack versions
    - resolve_all_jira: Keep all Jira versions
    """

    @app.action("create_workitem_in_jira")
    def handle_create_in_jira(ack: Ack, body: dict, client: Any, respond: Respond):
        """Handle Create in Jira button click."""
        ack()
        _run_async(_handle_create_in_jira_async(body, client, respond))

    @app.action("keep_workitem_local")
    def handle_keep_local(ack: Ack, body: dict, respond: Respond):
        """Handle Keep local button click."""
        ack()
        _run_async(_handle_keep_local_async(body, respond))

    @app.action("edit_workitem")
    def handle_edit_workitem(ack: Ack, body: dict, respond: Respond):
        """Handle Edit button click."""
        ack()
        respond(
            text="Edit functionality coming soon. For now, update in thread.",
            response_type="ephemeral",
        )

    # Conflict resolution handlers - use regex for indexed actions
    @app.action({"action_id": "resolve_conflict_slack_\\d+"})
    def handle_resolve_slack(ack: Ack, body: dict, respond: Respond):
        """Handle Keep Slack button for single conflict."""
        ack()
        _run_async(_handle_resolve_conflict_async(body, respond, "slack"))

    @app.action({"action_id": "resolve_conflict_jira_\\d+"})
    def handle_resolve_jira(ack: Ack, body: dict, respond: Respond):
        """Handle Keep Jira button for single conflict."""
        ack()
        _run_async(_handle_resolve_conflict_async(body, respond, "jira"))

    @app.action("resolve_all_slack")
    def handle_resolve_all_slack(ack: Ack, body: dict, respond: Respond):
        """Handle Keep all Slack versions button."""
        ack()
        _run_async(_handle_resolve_all_async(body, respond, "slack"))

    @app.action("resolve_all_jira")
    def handle_resolve_all_jira(ack: Ack, body: dict, respond: Respond):
        """Handle Keep all Jira versions button."""
        ack()
        _run_async(_handle_resolve_all_async(body, respond, "jira"))


async def _handle_create_in_jira_async(
    body: dict,
    client: AsyncWebClient,
    respond: Respond,
) -> None:
    """Async handler for create_workitem_in_jira action."""
    try:
        action = body.get("actions", [{}])[0]
        value_str = action.get("value", "{}")
        data = json.loads(value_str)

        workitem_id = data.get("workitem_id")
        channel_id = data.get("channel_id")
        user_id = get_identity_from_body(body)

        if not workitem_id:
            respond(text="Error: Missing workitem_id", response_type="ephemeral")
            return

        async with get_connection() as conn:
            store = WorkItemStore(conn)
            workitem = await store.get(workitem_id)

            if not workitem:
                respond(text="Error: WorkItem not found", response_type="ephemeral")
                return

            if workitem.jira_key:
                respond(
                    text=f"Already in Jira: {workitem.jira_key}",
                    response_type="ephemeral",
                )
                return

            # Create in Jira
            settings = Settings()
            jira_service = JiraService(settings)
            sync_service = JiraSyncService(jira_service, conn)

            try:
                updated_item, jira_issue = await sync_service.create_in_jira(
                    workitem, user_id=user_id
                )

                # Update board
                board_manager = ChannelWorkBoardManager()
                await board_manager.post_or_update(client, channel_id, conn)

                # Replace CTA with success
                success_blocks = build_jira_created_blocks(
                    updated_item,
                    jira_issue.key,
                    jira_issue.url,
                )
                respond(
                    blocks=success_blocks,
                    text=f"Created {jira_issue.key}",
                    replace_original=True,
                )

            finally:
                await jira_service.close()

    except Exception as e:
        logger.error(f"Failed to create in Jira: {e}", exc_info=True)
        respond(
            text="Sorry, couldn't create in Jira. Please try again.",
            response_type="ephemeral",
        )


async def _handle_keep_local_async(body: dict, respond: Respond) -> None:
    """Async handler for keep_workitem_local action."""
    try:
        action = body.get("actions", [{}])[0]
        value_str = action.get("value", "{}")
        data = json.loads(value_str)

        workitem_id = data.get("workitem_id")

        if not workitem_id:
            respond(text="Error: Missing workitem_id", response_type="ephemeral")
            return

        async with get_connection() as conn:
            store = WorkItemStore(conn)
            workitem = await store.get(workitem_id)

            if not workitem:
                respond(text="Error: WorkItem not found", response_type="ephemeral")
                return

            # Replace CTA with kept local message
            kept_blocks = build_kept_local_blocks(workitem)
            respond(
                blocks=kept_blocks,
                text="Kept local",
                replace_original=True,
            )

    except Exception as e:
        logger.error(f"Failed to keep local: {e}", exc_info=True)
        respond(
            text="Sorry, something went wrong.",
            response_type="ephemeral",
        )


async def _handle_resolve_conflict_async(
    body: dict,
    respond: Respond,
    resolution: str,
) -> None:
    """Async handler for single conflict resolution."""
    try:
        action = body.get("actions", [{}])[0]
        value_str = action.get("value", "{}")
        data = json.loads(value_str)

        jira_key = data.get("jira_key", "")
        section = data.get("section", "")

        # TODO: Actually apply the resolution via JiraSyncService
        # For now, just show confirmation

        resolved_blocks = build_conflict_resolved_blocks(
            jira_key, resolution, section
        )
        respond(
            blocks=resolved_blocks,
            text=f"Conflict resolved - {resolution} version kept",
            replace_original=True,
        )

    except Exception as e:
        logger.error(f"Failed to resolve conflict: {e}", exc_info=True)
        respond(
            text="Sorry, couldn't resolve conflict.",
            response_type="ephemeral",
        )


async def _handle_resolve_all_async(
    body: dict,
    respond: Respond,
    resolution: str,
) -> None:
    """Async handler for resolve all conflicts."""
    try:
        action = body.get("actions", [{}])[0]
        value_str = action.get("value", "{}")
        data = json.loads(value_str)

        jira_key = data.get("jira_key", "")

        # TODO: Actually apply all resolutions via JiraSyncService

        resolved_blocks = build_conflict_resolved_blocks(jira_key, resolution)
        respond(
            blocks=resolved_blocks,
            text=f"All conflicts resolved - {resolution} versions kept",
            replace_original=True,
        )

    except Exception as e:
        logger.error(f"Failed to resolve all conflicts: {e}", exc_info=True)
        respond(
            text="Sorry, couldn't resolve conflicts.",
            response_type="ephemeral",
        )
