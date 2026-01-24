"""Preflight sync button handlers (Phase 29.4).

Handles button interactions from preflight conflict UI:
- preflight_proceed: Execute pending action despite conflict
- preflight_pull_only: Sync from Jira, don't execute
- preflight_use_jira: Use Jira version for conflicting fields
- preflight_use_channel: Force local version (override Jira)
- preflight_cancel: Abort operation
- preflight_link_existing: Link to existing ticket (for create duplicates)
"""

import json
import logging
from typing import Optional

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def handle_preflight_proceed(ack, body: dict, client: WebClient) -> None:
    """Handle preflight_proceed button - execute pending action.

    Proceeds with the originally intended action despite preflight warning.
    """
    ack()
    _run_async(_handle_preflight_proceed_async(body, client))


async def _handle_preflight_proceed_async(body: dict, client: WebClient) -> None:
    """Execute pending action after user confirms proceed."""
    from src.slack.session import SessionIdentity
    from src.graph.runner import get_runner
    from src.skills.jira_create import jira_create
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.db import get_connection
    from src.slack.handlers.draft_blocks import (
        post_error_actions,
        update_preview_to_created,
    )

    channel_id = body.get("channel", {}).get("id")
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
    message_ts = body.get("message", {}).get("ts")
    user_id = body.get("user", {}).get("id")
    team_id = body.get("team", {}).get("id", "unknown")

    # Parse button value
    action = body.get("actions", [{}])[0]
    button_value = action.get("value", "{}")

    try:
        payload = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse preflight button payload: {button_value}")
        return

    pending_action = payload.get("pending_action", {})
    action_type = pending_action.get("action_type", "")
    jira_key = payload.get("jira_key") or pending_action.get("ticket_key")
    session_id = payload.get("session_id", "")
    draft_hash = payload.get("draft_hash", "")

    logger.info(
        "Preflight proceed requested",
        extra={
            "channel_id": channel_id,
            "action_type": action_type,
            "jira_key": jira_key,
            "user_id": user_id,
        }
    )

    # Update the preflight message to show processing
    try:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Processing...",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": ":hourglass: Processing..."},
                }
            ],
        )
    except Exception as e:
        logger.warning(f"Failed to update preflight message: {e}")

    # Handle based on action type
    if action_type == "create" or session_id:
        # Create flow - need to proceed with ticket creation
        await _execute_create_action(
            client=client,
            channel_id=channel_id,
            thread_ts=thread_ts,
            message_ts=message_ts,
            user_id=user_id,
            team_id=team_id,
            session_id=session_id,
            draft_hash=draft_hash,
        )
    elif action_type == "update":
        # Update flow - execute pending update
        await _execute_update_action(
            client=client,
            channel_id=channel_id,
            thread_ts=thread_ts,
            message_ts=message_ts,
            user_id=user_id,
            team_id=team_id,
            pending_action=pending_action,
        )
    else:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f"Unknown action type: {action_type}",
            blocks=[],
        )


async def _execute_create_action(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    message_ts: str,
    user_id: str,
    team_id: str,
    session_id: str,
    draft_hash: str,
) -> None:
    """Execute ticket creation after preflight proceed."""
    from src.slack.session import SessionIdentity
    from src.graph.runner import get_runner
    from src.skills.jira_create import jira_create
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.db import get_connection
    from src.slack.handlers.draft_blocks import update_preview_to_created

    # Parse session_id to get identity
    if not session_id:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Session expired. Please start a new draft.",
            blocks=[],
        )
        return

    parts = session_id.split(":")
    if len(parts) != 3:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Invalid session. Please start a new draft.",
            blocks=[],
        )
        return

    identity = SessionIdentity(
        team_id=parts[0],
        channel_id=parts[1],
        thread_ts=parts[2],
    )

    # Get draft from runner
    runner = get_runner(identity)
    state = await runner._get_current_state()
    draft = state.get("draft")

    if not draft:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Draft not found. Please start a new draft.",
            blocks=[],
        )
        return

    # Create the ticket
    settings = get_settings()
    jira_service = JiraService(settings)

    async with get_connection() as conn:
        try:
            # Get Slack permalink
            slack_permalink = ""
            try:
                from src.context.jira_linker import JiraLinker
                linker = JiraLinker(client, jira_service)
                slack_permalink = linker.get_thread_permalink(channel_id, thread_ts)
            except Exception as e:
                logger.warning(f"Failed to get Slack permalink: {e}")

            create_result = await jira_create(
                session_id=session_id,
                draft=draft,
                approved_by=user_id,
                jira_service=jira_service,
                conn=conn,
                settings=settings,
                slack_permalink=slack_permalink,
                channel_id=channel_id,
                thread_ts=thread_ts,
            )

            if create_result.success:
                # Update message to show success
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text=f":white_check_mark: Ticket created: <{create_result.jira_url}|{create_result.jira_key}>",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f":white_check_mark: Ticket created: <{create_result.jira_url}|{create_result.jira_key}>",
                            },
                        }
                    ],
                )

                # Register in channel Jira registry
                try:
                    from src.db.jira_registry import JiraRegistryStore
                    registry = JiraRegistryStore(conn)
                    await registry.create_tables()
                    await registry.register(
                        channel_id=channel_id,
                        jira_key=create_result.jira_key,
                        link_type="owned",
                        linked_by=user_id,
                        summary=draft.title if draft else None,
                    )
                except Exception as e:
                    logger.warning(f"Failed to register ticket: {e}")

            else:
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text=f":x: Failed to create ticket: {create_result.error}",
                    blocks=[],
                )

        except Exception as e:
            logger.error(f"Failed to create ticket after preflight proceed: {e}")
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f":x: Failed to create ticket: {str(e)}",
                blocks=[],
            )
        finally:
            await jira_service.close()


async def _execute_update_action(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    message_ts: str,
    user_id: str,
    team_id: str,
    pending_action: dict,
) -> None:
    """Execute ticket update after preflight proceed."""
    from src.jira.client import JiraService
    from src.config.settings import get_settings

    ticket_key = pending_action.get("ticket_key")
    proposed_content = pending_action.get("proposed_content", "")

    if not ticket_key or not proposed_content:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Missing update data. Please try again.",
            blocks=[],
        )
        return

    settings = get_settings()
    jira_service = JiraService(settings)

    try:
        # Fetch existing description and append
        existing_issue = await jira_service.get_issue(ticket_key)
        existing_description = existing_issue.description or ""

        new_description = existing_description
        if new_description:
            new_description += "\n\n---\n\n"
        new_description += proposed_content

        # Update the issue
        await jira_service.update_issue(
            ticket_key,
            description=new_description,
        )

        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":white_check_mark: Updated *{ticket_key}*",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":white_check_mark: Updated *{ticket_key}*",
                    },
                }
            ],
        )

    except Exception as e:
        logger.error(f"Failed to update ticket after preflight proceed: {e}")
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":x: Failed to update *{ticket_key}*: {str(e)}",
            blocks=[],
        )
    finally:
        await jira_service.close()


def handle_preflight_pull_only(ack, body: dict, client: WebClient) -> None:
    """Handle preflight_pull_only button - sync from Jira only.

    Updates local state with fresh Jira data, doesn't execute the operation.
    """
    ack()
    _run_async(_handle_preflight_pull_only_async(body, client))


async def _handle_preflight_pull_only_async(body: dict, client: WebClient) -> None:
    """Sync from Jira without executing the pending action."""
    from src.db.jira_registry import JiraRegistryStore
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.db import get_connection
    from datetime import datetime

    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")

    # Parse button value
    action = body.get("actions", [{}])[0]
    button_value = action.get("value", "{}")

    try:
        payload = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse preflight button payload: {button_value}")
        return

    jira_key = payload.get("jira_key")

    if not jira_key:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="No ticket specified.",
            blocks=[],
        )
        return

    logger.info(
        "Preflight pull only requested",
        extra={
            "channel_id": channel_id,
            "jira_key": jira_key,
        }
    )

    settings = get_settings()
    jira_service = JiraService(settings)

    try:
        # Fetch fresh data from Jira
        issue = await jira_service.get_issue(jira_key)

        # Update registry
        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)
            await registry.create_tables()
            await registry.update_from_jira(
                channel_id=channel_id,
                jira_key=jira_key,
                summary=issue.summary,
                status=issue.status,
                assignee=issue.assignee,
                issue_type=issue.issue_type or "story",
                jira_updated=datetime.now(),
            )

        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":arrows_counterclockwise: Synced *{jira_key}* from Jira. Local state updated.",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":arrows_counterclockwise: Synced *{jira_key}* from Jira.\n\nLocal state updated. Operation cancelled.",
                    },
                }
            ],
        )

    except Exception as e:
        logger.error(f"Failed to sync from Jira: {e}")
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":x: Failed to sync from Jira: {str(e)}",
            blocks=[],
        )
    finally:
        await jira_service.close()


def handle_preflight_use_jira(ack, body: dict, client: WebClient) -> None:
    """Handle preflight_use_jira button - use Jira version for conflicts.

    Resolves conflict by accepting Jira's version, then executes action.
    """
    ack()
    _run_async(_handle_preflight_use_jira_async(body, client))


async def _handle_preflight_use_jira_async(body: dict, client: WebClient) -> None:
    """Use Jira version for conflicting fields, then execute action."""
    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")

    # Parse button value
    action = body.get("actions", [{}])[0]
    button_value = action.get("value", "{}")

    try:
        payload = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse preflight button payload: {button_value}")
        return

    jira_key = payload.get("jira_key")

    logger.info(
        "Preflight use Jira requested",
        extra={
            "channel_id": channel_id,
            "jira_key": jira_key,
        }
    )

    # For use_jira, we sync from Jira first (same as pull_only)
    # then inform user the operation was skipped because we used Jira's version
    await _handle_preflight_pull_only_async(body, client)


def handle_preflight_use_channel(ack, body: dict, client: WebClient) -> None:
    """Handle preflight_use_channel button - force local version.

    Overrides Jira with channel/local version.
    """
    ack()
    _run_async(_handle_preflight_use_channel_async(body, client))


async def _handle_preflight_use_channel_async(body: dict, client: WebClient) -> None:
    """Force local version, override Jira values."""
    # Same as proceed - execute the pending action
    await _handle_preflight_proceed_async(body, client)


def handle_preflight_cancel(ack, body: dict, client: WebClient) -> None:
    """Handle preflight_cancel button - abort operation.

    Simply dismisses the preflight UI without any action.
    """
    ack()
    _run_async(_handle_preflight_cancel_async(body, client))


async def _handle_preflight_cancel_async(body: dict, client: WebClient) -> None:
    """Cancel the operation and dismiss preflight UI."""
    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")

    logger.info(
        "Preflight cancelled",
        extra={"channel_id": channel_id}
    )

    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text="Operation cancelled.",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_Operation cancelled._"},
            }
        ],
    )


def handle_preflight_link_existing(ack, body: dict, client: WebClient) -> None:
    """Handle preflight_link_existing button - link to existing ticket.

    For idempotent create scenarios: links thread to existing ticket instead.
    """
    ack()
    _run_async(_handle_preflight_link_existing_async(body, client))


async def _handle_preflight_link_existing_async(body: dict, client: WebClient) -> None:
    """Link thread to existing ticket instead of creating new one."""
    from src.slack.thread_bindings import get_binding_store
    from src.db.jira_registry import JiraRegistryStore
    from src.db import get_connection
    from src.config.settings import get_settings

    channel_id = body.get("channel", {}).get("id")
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
    message_ts = body.get("message", {}).get("ts")
    user_id = body.get("user", {}).get("id")

    # Parse button value
    action = body.get("actions", [{}])[0]
    button_value = action.get("value", "{}")

    try:
        payload = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse preflight button payload: {button_value}")
        return

    existing_key = payload.get("existing_key")

    if not existing_key:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="No existing ticket to link.",
            blocks=[],
        )
        return

    logger.info(
        "Preflight link existing requested",
        extra={
            "channel_id": channel_id,
            "existing_key": existing_key,
        }
    )

    try:
        # Bind thread to existing ticket
        binding_store = get_binding_store()
        await binding_store.bind(
            channel_id=channel_id,
            thread_ts=thread_ts,
            issue_key=existing_key,
            bound_by=user_id,
        )

        # Get URL for message
        settings = get_settings()
        jira_url = f"{settings.jira_url.rstrip('/')}/browse/{existing_key}"

        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":link: Linked this thread to existing ticket: <{jira_url}|{existing_key}>",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":link: Linked this thread to existing ticket: <{jira_url}|{existing_key}>",
                    },
                }
            ],
        )

    except Exception as e:
        logger.error(f"Failed to link to existing ticket: {e}")
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":x: Failed to link to {existing_key}: {str(e)}",
            blocks=[],
        )


def register_preflight_handlers(app) -> None:
    """Register all preflight button handlers with the Slack app.

    Args:
        app: Slack Bolt App instance.
    """
    app.action("preflight_proceed")(handle_preflight_proceed)
    app.action("preflight_pull_only")(handle_preflight_pull_only)
    app.action("preflight_use_jira")(handle_preflight_use_jira)
    app.action("preflight_use_channel")(handle_preflight_use_channel)
    app.action("preflight_cancel")(handle_preflight_cancel)
    app.action("preflight_link_existing")(handle_preflight_link_existing)
    # View existing is just a link button - no handler needed (opens URL)
    # preflight_show_diff, preflight_remove_tracking, preflight_reopen can be added later

    logger.info("Preflight handlers registered")
