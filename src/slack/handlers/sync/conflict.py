"""Sync conflict resolution handlers.

Handles sync button actions for conflict resolution:
- sync_use_slack - Apply Slack value to Jira
- sync_use_jira - Keep Jira value
- sync_apply_all - Apply all auto-apply changes
- sync_skip - Skip a conflict
- sync_cancel - Cancel sync
- sync_merge - Open merge modal
"""

import json
import logging
import asyncio

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


def handle_sync_apply_all(ack, body, client):
    """Handle sync_apply_all button click.

    Applies all auto-apply changes.
    """
    ack()

    asyncio.create_task(_handle_sync_apply_all_async(body, client))


async def _handle_sync_apply_all_async(body, client):
    """Async handler for applying all changes."""
    from src.db import get_connection
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.slack.sync_engine import SyncEngine, ChangeDetection
    from src.slack.channel_tracker import trigger_board_refresh

    action = body["actions"][0]
    data = json.loads(action["value"])
    changes_data = data.get("changes", [])

    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    try:
        settings = get_settings()
        jira_service = JiraService(settings)
        jira_url = settings.jira_url.rstrip("/")

        # Reconstruct ChangeDetection objects
        changes = [
            ChangeDetection(
                issue_key=c["issue_key"],
                field=c["field"],
                slack_value=c.get("slack_value"),
                jira_value=c.get("jira_value"),
                change_type=c.get("change_type", "slack_ahead"),
                confidence=0.9,
                source=f"decision:{c.get('source_ts')}" if c.get("source_ts") else "manual",
                source_ts=c.get("source_ts"),
            )
            for c in changes_data
        ]

        async with get_connection() as conn:
            engine = SyncEngine(jira_service, jira_url)
            results = await engine.apply_changes(changes, channel_id, conn)

        await jira_service.close()

        # Update message with results
        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count

        if fail_count == 0:
            text = f":white_check_mark: Applied {success_count} change{'s' if success_count != 1 else ''} to Jira"
        else:
            text = f":white_check_mark: Applied {success_count}, :x: {fail_count} failed"

        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=text,
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": text}
            }],
        )

        # Trigger board refresh
        await trigger_board_refresh(channel_id, jira_url)

    except Exception as e:
        logger.error(f"Failed to apply changes: {e}", exc_info=True)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":x: Failed to apply changes: {str(e)}",
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":x: Failed to apply changes: {str(e)}"}
            }],
        )


def handle_sync_use_slack(ack, body, client):
    """Handle sync_use_slack button click - apply Slack value to Jira."""
    ack()

    asyncio.create_task(_handle_sync_resolution_async(body, client, use_slack=True))


def handle_sync_use_jira(ack, body, client):
    """Handle sync_use_jira button click - keep Jira value."""
    ack()

    asyncio.create_task(_handle_sync_resolution_async(body, client, use_slack=False))


async def _handle_sync_resolution_async(body, client, use_slack: bool):
    """Async handler for conflict resolution."""
    from src.db import get_connection
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.slack.channel_tracker import ChannelIssueTracker, trigger_board_refresh

    action = body["actions"][0]
    data = json.loads(action["value"])

    issue_key = data.get("issue_key")
    field = data.get("field")
    value = data.get("value")
    source_ts = data.get("source_ts")

    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    try:
        settings = get_settings()
        jira_url = settings.jira_url.rstrip("/")

        if use_slack and value:
            # Apply Slack value to Jira
            jira_service = JiraService(settings)

            if field == "status":
                # Use transition API
                from src.slack.handlers.jira_commands import _transition_issue
                await _transition_issue(jira_service, issue_key, value)
            elif field in ("summary", "description"):
                await jira_service.update_issue(issue_key, {field: value})
            elif field == "priority":
                await jira_service.update_issue(issue_key, {"priority": {"name": value}})

            await jira_service.close()
            result_text = f":white_check_mark: *{issue_key}* {field} updated to `{value}`"
        else:
            # Accept Jira value - update tracker
            async with get_connection() as conn:
                tracker = ChannelIssueTracker(conn)
                await tracker.update_sync_status(
                    channel_id,
                    issue_key,
                    status=value if field == "status" else None,
                    summary=value if field == "summary" else None,
                )
            result_text = f":white_check_mark: *{issue_key}* synced with Jira value"

        # Update message
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=result_text,
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": result_text}
            }],
        )

        # Trigger board refresh
        await trigger_board_refresh(channel_id, jira_url)

    except Exception as e:
        logger.error(f"Conflict resolution failed: {e}", exc_info=True)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":x: Failed to resolve: {str(e)}",
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":x: Failed to resolve: {str(e)}"}
            }],
        )


def handle_sync_skip(ack, body, client):
    """Handle sync_skip button click - skip this conflict."""
    ack()

    action = body["actions"][0]
    data = json.loads(action["value"])

    issue_key = data.get("issue_key")
    field = data.get("field")

    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    # Update message to show skipped
    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Skipped {issue_key} {field}",
        blocks=[{
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"~{issue_key} {field}~ Skipped"}
        }],
    )


def handle_sync_cancel(ack, body, client):
    """Handle sync_cancel button click."""
    ack()

    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text="Sync cancelled",
        blocks=[{
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Sync cancelled"}
        }],
    )


def handle_sync_merge(ack, body, client):
    """Handle sync_merge button click - open merge modal."""
    ack()

    action = body["actions"][0]
    data = json.loads(action["value"])

    issue_key = data.get("issue_key")
    field = data.get("field")
    slack_value = data.get("slack_value", "")
    jira_value = data.get("jira_value", "")

    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    trigger_id = body.get("trigger_id")

    if not trigger_id:
        logger.warning("No trigger_id for merge modal")
        return

    # Build modal with both versions for manual merge
    modal = {
        "type": "modal",
        "callback_id": "sync_merge_modal",
        "private_metadata": json.dumps({
            "issue_key": issue_key,
            "field": field,
            "channel_id": channel_id,
            "message_ts": message_ts,
        }),
        "title": {
            "type": "plain_text",
            "text": f"Merge {field}",
        },
        "submit": {
            "type": "plain_text",
            "text": "Save Merged Version",
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel",
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{issue_key}* - {field}\n\nCombine both versions below:"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Slack version:*\n```{slack_value[:1000] if slack_value else '(empty)'}```"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Jira version:*\n```{jira_value[:1000] if jira_value else '(empty)'}```"
                }
            },
            {
                "type": "input",
                "block_id": "merged_content",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "content",
                    "multiline": True,
                    "initial_value": jira_value or slack_value or "",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Enter merged content..."
                    }
                },
                "label": {
                    "type": "plain_text",
                    "text": "Merged Content"
                }
            }
        ]
    }

    client.views_open(trigger_id=trigger_id, view=modal)


def handle_sync_merge_submit(ack, body, view, client):
    """Handle sync_merge_modal submission."""
    ack()

    asyncio.create_task(_handle_sync_merge_submit_async(body, view, client))


async def _handle_sync_merge_submit_async(body, view, client):
    """Async handler for merge modal submission."""
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.slack.channel_tracker import trigger_board_refresh

    private_metadata = json.loads(view.get("private_metadata", "{}"))
    issue_key = private_metadata.get("issue_key")
    field = private_metadata.get("field")
    channel_id = private_metadata.get("channel_id")
    message_ts = private_metadata.get("message_ts")

    # Get merged content from form
    values = view.get("values", {})
    merged_content = values.get("merged_content", {}).get("content", {}).get("value", "")

    if not merged_content:
        logger.warning("Empty merged content submitted")
        return

    try:
        settings = get_settings()
        jira_service = JiraService(settings)
        jira_url = settings.jira_url.rstrip("/")

        # Apply merged content to Jira
        if field in ("summary", "description"):
            await jira_service.update_issue(issue_key, {field: merged_content})
        elif field == "priority":
            await jira_service.update_issue(issue_key, {"priority": {"name": merged_content}})

        await jira_service.close()

        # Update original message
        result_text = f":white_check_mark: *{issue_key}* {field} updated with merged content"
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=result_text,
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": result_text}
            }],
        )

        # Trigger board refresh
        await trigger_board_refresh(channel_id, jira_url)

    except Exception as e:
        logger.error(f"Merge submit failed: {e}", exc_info=True)
        # Post error as new message since modal is closed
        client.chat_postMessage(
            channel=channel_id,
            text=f":x: Failed to apply merged content to *{issue_key}*: {str(e)}",
        )


def handle_sync_track_all_button(ack, body, client):
    """Handle sync_track_all button click (Bolt handler)."""
    ack()

    action = body["actions"][0]
    data = json.loads(action["value"])
    channel_id = data.get("channel_id")
    keys = data.get("keys", [])
    response_url = body.get("response_url", "")
    user_id = body.get("user", {}).get("id", "unknown")

    from src.slack.handlers.sync.manual import handle_sync_track_all
    asyncio.create_task(
        handle_sync_track_all(client, channel_id, user_id, keys, response_url)
    )


def handle_sync_remove_button(ack, body, client):
    """Handle sync_remove button click (Bolt handler)."""
    ack()

    action = body["actions"][0]
    data = json.loads(action["value"])
    channel_id = data.get("channel_id")
    key = data.get("key")
    response_url = body.get("response_url", "")
    user_id = body.get("user", {}).get("id", "unknown")

    from src.slack.handlers.sync.manual import handle_sync_remove
    asyncio.create_task(
        handle_sync_remove(client, channel_id, user_id, key, response_url)
    )


def handle_sync_ignore_button(ack, body, client):
    """Handle sync_ignore button click (Bolt handler)."""
    ack()

    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    # Just dismiss the missing locally section
    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text="Sync dismissed",
        blocks=[{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":white_check_mark: Sync complete (missing issues ignored)",
            }
        }],
    )


async def show_conflict_detail(
    change,
    channel_id: str,
    client: WebClient,
    jira_base_url: str = "",
) -> None:
    """Show detailed conflict resolution UI for a single change.

    Args:
        change: ChangeDetection object
        channel_id: Channel to post in
        client: Slack WebClient
        jira_base_url: Base URL for Jira links
    """
    from src.slack.handlers.sync.blocks import build_full_conflict_blocks

    blocks = build_full_conflict_blocks(change, jira_base_url)

    client.chat_postMessage(
        channel=channel_id,
        text=f"Conflict: {change.issue_key} {change.field}",
        blocks=blocks,
    )
