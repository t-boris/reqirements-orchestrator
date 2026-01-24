"""Sync command handlers for Jira synchronization.

Handles /maro sync command and sync-related button actions:
- /maro sync - Show pending changes summary
- /maro sync --auto - Apply obvious changes automatically
- sync_use_slack - Apply Slack value to Jira (conflict resolution)
- sync_use_jira - Keep Jira value (conflict resolution)
- sync_apply_all - Apply all auto-apply changes
"""
import json
import logging
from typing import Optional

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


def build_sync_summary_blocks(
    channel_name: str,
    plan,
    jira_base_url: str = "",
) -> list[dict]:
    """Build Slack blocks for sync summary.

    Args:
        channel_name: Channel name for display
        plan: SyncPlan from SyncEngine
        jira_base_url: Base URL for Jira links

    Returns:
        List of Slack block objects
    """
    from src.slack.sync_engine import SyncPlan

    blocks = []

    # Header
    total_changes = len(plan.auto_apply) + len(plan.needs_review)
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Jira Sync for #{channel_name}",
            "emoji": True,
        }
    })

    # No changes case
    if total_changes == 0:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":white_check_mark: *All tracked issues are in sync with Jira*"
            }
        })
        if plan.in_sync:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"{len(plan.in_sync)} issue{'s' if len(plan.in_sync) != 1 else ''} verified in sync"
                }]
            })
        return blocks

    # Auto-apply section
    if plan.auto_apply:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Auto-apply ({len(plan.auto_apply)} change{'s' if len(plan.auto_apply) != 1 else ''})*\n"
                        "These will be applied automatically:"
            }
        })

        for change in plan.auto_apply[:10]:  # Limit to 10 for UI
            icon = ":arrow_right:" if change.change_type == "slack_ahead" else ":arrow_left:"
            if jira_base_url:
                link = f"<{jira_base_url}/browse/{change.issue_key}|{change.issue_key}>"
            else:
                link = f"*{change.issue_key}*"

            if change.change_type == "slack_ahead":
                change_text = f"{icon} {link}: {change.field} `{change.jira_value or '(none)'}` -> `{change.slack_value}`"
            else:
                change_text = f"{icon} {link}: {change.field} updated in Jira to `{change.jira_value}`"

            source_hint = ""
            if change.source.startswith("decision:"):
                source_hint = " _(from decision)_"
            elif change.source == "jira_update":
                source_hint = " _(Jira update)_"

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": change_text + source_hint}
            })

    # Needs review section (conflicts)
    if plan.needs_review:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Needs Review ({len(plan.needs_review)} conflict{'s' if len(plan.needs_review) != 1 else ''})*\n"
                        "These require your decision:"
            }
        })

        for i, change in enumerate(plan.needs_review[:5]):  # Limit to 5 conflicts
            if jira_base_url:
                link = f"<{jira_base_url}/browse/{change.issue_key}|{change.issue_key}>"
            else:
                link = f"*{change.issue_key}*"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: {link}: *{change.field}*\n"
                            f"  - Slack: `{change.slack_value or '(none)'}`\n"
                            f"  - Jira: `{change.jira_value or '(none)'}`"
                }
            })

            # Add resolution buttons for each conflict
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Use Slack"},
                        "action_id": f"sync_use_slack_{i}",
                        "value": json.dumps({
                            "issue_key": change.issue_key,
                            "field": change.field,
                            "value": change.slack_value,
                            "source_ts": change.source_ts,
                        }),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Use Jira"},
                        "action_id": f"sync_use_jira_{i}",
                        "value": json.dumps({
                            "issue_key": change.issue_key,
                            "field": change.field,
                            "value": change.jira_value,
                        }),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Skip"},
                        "action_id": f"sync_skip_{i}",
                        "value": json.dumps({
                            "issue_key": change.issue_key,
                            "field": change.field,
                        }),
                    },
                ]
            })

    # Action buttons
    blocks.append({"type": "divider"})
    action_elements = []

    if plan.auto_apply:
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": f"Apply {len(plan.auto_apply)} Changes"},
            "action_id": "sync_apply_all",
            "value": json.dumps({
                "changes": [
                    {
                        "issue_key": c.issue_key,
                        "field": c.field,
                        "slack_value": c.slack_value,
                        "jira_value": c.jira_value,
                        "change_type": c.change_type,
                        "source_ts": c.source_ts,
                    }
                    for c in plan.auto_apply
                ]
            }),
            "style": "primary",
        })

    action_elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Cancel"},
        "action_id": "sync_cancel",
        "value": "cancel",
    })

    blocks.append({
        "type": "actions",
        "elements": action_elements,
    })

    return blocks


def build_conflict_detail_blocks(
    change,
    jira_base_url: str = "",
    source_preview: str = "",
) -> list[dict]:
    """Build detailed conflict resolution blocks with side-by-side comparison.

    Args:
        change: ChangeDetection object
        jira_base_url: Base URL for Jira links
        source_preview: Preview text from source message

    Returns:
        List of Slack block objects
    """
    blocks = []

    if jira_base_url:
        link = f"<{jira_base_url}/browse/{change.issue_key}|{change.issue_key}>"
    else:
        link = f"*{change.issue_key}*"

    # Header
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f":warning: *Conflict: {link} {change.field}*"
        }
    })

    # Slack version
    slack_text = change.slack_value or "(no value)"
    if len(slack_text) > 500:
        slack_text = slack_text[:497] + "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Slack version*{' (from decision)' if change.source.startswith('decision:') else ''}:\n>{slack_text}"
        }
    })

    # Jira version
    jira_text = change.jira_value or "(no value)"
    if len(jira_text) > 500:
        jira_text = jira_text[:497] + "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Jira version*:\n>{jira_text}"
        }
    })

    # Action buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use Slack Version"},
                "action_id": "sync_use_slack",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "value": change.slack_value,
                    "source_ts": change.source_ts,
                }),
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use Jira Version"},
                "action_id": "sync_use_jira",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "value": change.jira_value,
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Skip"},
                "action_id": "sync_skip",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                }),
            },
        ]
    })

    return blocks


async def handle_maro_sync(
    channel_id: str,
    client: WebClient,
    user_id: str,
    auto_mode: bool = False,
) -> None:
    """Handle /maro sync command.

    Args:
        channel_id: Slack channel ID
        client: Slack WebClient
        user_id: User who invoked command
        auto_mode: If True, apply auto-apply changes immediately
    """
    from src.db import get_connection
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.slack.sync_engine import SyncEngine

    try:
        settings = get_settings()
        jira_service = JiraService(settings)
        jira_url = settings.jira_url.rstrip("/")

        # Get channel name
        try:
            info = client.conversations_info(channel=channel_id)
            channel_name = info.get("channel", {}).get("name", channel_id)
        except Exception:
            channel_name = channel_id

        async with get_connection() as conn:
            engine = SyncEngine(jira_service, jira_url)
            plan = await engine.detect_changes(channel_id, conn)

            if auto_mode and plan.auto_apply:
                # Apply changes immediately
                results = await engine.apply_changes(plan.auto_apply, channel_id, conn)

                # Build results message
                success_count = sum(1 for r in results if r.success)
                fail_count = len(results) - success_count

                if fail_count == 0:
                    text = f":white_check_mark: Applied {success_count} change{'s' if success_count != 1 else ''} to Jira"
                else:
                    text = f":white_check_mark: Applied {success_count} change{'s' if success_count != 1 else ''}, :x: {fail_count} failed"

                client.chat_postMessage(
                    channel=channel_id,
                    text=text,
                )

                # Show any remaining conflicts
                if plan.needs_review:
                    blocks = build_sync_summary_blocks(channel_name, plan, jira_url)
                    client.chat_postMessage(
                        channel=channel_id,
                        text="Sync conflicts need review",
                        blocks=blocks,
                    )
            else:
                # Show sync summary
                blocks = build_sync_summary_blocks(channel_name, plan, jira_url)
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"Jira Sync for #{channel_name}",
                    blocks=blocks,
                )

        await jira_service.close()

    except Exception as e:
        logger.error(f"Sync command failed: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            text="Sorry, I couldn't check sync status. Please try again.",
        )


def handle_sync_apply_all(ack, body, client):
    """Handle sync_apply_all button click.

    Applies all auto-apply changes.
    """
    ack()

    import asyncio
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

    import asyncio
    asyncio.create_task(_handle_sync_resolution_async(body, client, use_slack=True))


def handle_sync_use_jira(ack, body, client):
    """Handle sync_use_jira button click - keep Jira value."""
    ack()

    import asyncio
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

    import asyncio
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


def build_full_conflict_blocks(
    change,
    jira_base_url: str = "",
) -> list[dict]:
    """Build full-page conflict resolution blocks.

    Shows detailed side-by-side comparison with all resolution options.

    Args:
        change: ChangeDetection object
        jira_base_url: Base URL for Jira links

    Returns:
        List of Slack block objects
    """
    blocks = []

    if jira_base_url:
        link = f"<{jira_base_url}/browse/{change.issue_key}|{change.issue_key}>"
    else:
        link = f"*{change.issue_key}*"

    # Header with warning
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Conflict: {change.issue_key} {change.field}",
            "emoji": True,
        }
    })

    # Context about the conflict
    source_info = ""
    if change.source.startswith("decision:"):
        source_info = " (from architecture decision)"
    elif change.source == "jira_update":
        source_info = " (updated in Jira)"

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Conflict detected{source_info} - choose which version to keep"
        }]
    })

    blocks.append({"type": "divider"})

    # Slack version section
    slack_text = change.slack_value or "(no value)"
    if len(slack_text) > 2000:
        slack_text = slack_text[:1997] + "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Slack version:*"
        }
    })
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f">{slack_text.replace(chr(10), chr(10) + '>')}"
        }
    })

    blocks.append({"type": "divider"})

    # Jira version section
    jira_text = change.jira_value or "(no value)"
    if len(jira_text) > 2000:
        jira_text = jira_text[:1997] + "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Jira version:*"
        }
    })
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f">{jira_text.replace(chr(10), chr(10) + '>')}"
        }
    })

    blocks.append({"type": "divider"})

    # Resolution buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use Slack Version"},
                "action_id": "sync_use_slack",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "value": change.slack_value,
                    "source_ts": change.source_ts,
                }),
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use Jira Version"},
                "action_id": "sync_use_jira",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "value": change.jira_value,
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Merge..."},
                "action_id": "sync_merge",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                    "slack_value": change.slack_value,
                    "jira_value": change.jira_value,
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Skip"},
                "action_id": "sync_skip",
                "value": json.dumps({
                    "issue_key": change.issue_key,
                    "field": change.field,
                }),
            },
        ]
    })

    return blocks


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
    blocks = build_full_conflict_blocks(change, jira_base_url)

    client.chat_postMessage(
        channel=channel_id,
        text=f"Conflict: {change.issue_key} {change.field}",
        blocks=blocks,
    )


# =============================================================================
# New Diagnostic Sync Command (Phase 29-03)
# =============================================================================


async def handle_sync_command(
    client: WebClient,
    channel_id: str,
    user_id: str,
    thread_ts: Optional[str] = None,
) -> None:
    """Handle /maro sync diagnostic command.

    Uses the new JiraSyncService for comprehensive reconciliation report.

    1. Post initial "Syncing..." message
    2. Run JiraSyncService.sync_channel()
    3. Update message with full report

    Args:
        client: Slack WebClient
        channel_id: Slack channel ID
        user_id: User who invoked command
        thread_ts: Optional thread timestamp for response
    """
    from src.db import get_connection
    from src.db.jira_registry import JiraRegistryStore
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.sync.jira_sync import JiraSyncService
    from src.slack.blocks.sync import build_sync_report_blocks

    # Post initial "Syncing..." message
    msg = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=":arrows_counterclockwise: Syncing with Jira...",
    )
    message_ts = msg.get("ts")

    jira_service = None
    try:
        settings = get_settings()
        jira_service = JiraService(settings)
        jira_url = settings.jira_url.rstrip("/")

        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)
            sync_service = JiraSyncService(jira_service, registry)

            # Run sync
            result = await sync_service.sync_channel(channel_id)

        # Build report blocks
        blocks = build_sync_report_blocks(result, jira_base_url=jira_url)

        # Update message with full report
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Sync report",
            blocks=blocks,
        )

        logger.info(
            "Sync command completed",
            extra={
                "channel_id": channel_id,
                "user_id": user_id,
                "total_checked": result.total_checked,
                "changed": len(result.changed),
                "missing_locally": len(result.missing_locally),
                "local_only": len(result.local_only),
            },
        )

    except Exception as e:
        logger.error(f"Sync command failed: {e}", exc_info=True)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":x: Sync failed: {str(e)}",
            blocks=[{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":x: Sync failed: {str(e)}",
                }
            }],
        )
    finally:
        if jira_service:
            await jira_service.close()


async def handle_sync_track_all(
    client: WebClient,
    channel_id: str,
    user_id: str,
    keys: list[str],
    response_url: str,
) -> None:
    """Handle 'Track all' button click.

    Register all provided keys as 'tracked' in registry.
    Update original message to show success.

    Args:
        client: Slack WebClient
        channel_id: Slack channel ID
        user_id: User who clicked
        keys: List of Jira issue keys to track
        response_url: Response URL for updating original message
    """
    from src.db import get_connection
    from src.db.jira_registry import JiraRegistryStore

    try:
        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)

            for key in keys:
                await registry.register(
                    channel_id=channel_id,
                    jira_key=key,
                    link_type="tracked",
                    linked_by=user_id,
                )

        logger.info(
            "Tracked all missing issues",
            extra={
                "channel_id": channel_id,
                "user_id": user_id,
                "keys": keys,
                "count": len(keys),
            },
        )

        # Update via response_url (for interactive message updates)
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                response_url,
                json={
                    "replace_original": True,
                    "text": f":white_check_mark: Tracked {len(keys)} issue{'s' if len(keys) != 1 else ''}",
                    "blocks": [{
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":white_check_mark: Tracked {len(keys)} issue{'s' if len(keys) != 1 else ''}: {', '.join(keys[:5])}{'...' if len(keys) > 5 else ''}",
                        }
                    }],
                },
            )

    except Exception as e:
        logger.error(f"Failed to track issues: {e}", exc_info=True)
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                response_url,
                json={
                    "replace_original": False,
                    "text": f":x: Failed to track issues: {str(e)}",
                },
            )


async def handle_sync_track_selected(
    client: WebClient,
    channel_id: str,
    user_id: str,
    keys: list[str],
) -> None:
    """Handle 'Track selected' - show modal with checkboxes.

    Args:
        client: Slack WebClient
        channel_id: Channel ID
        user_id: User ID
        keys: Available keys to select from
    """
    # This would open a modal - for now just track all
    # TODO: Implement modal selection if needed
    logger.info(
        "Track selected triggered - using track all for now",
        extra={
            "channel_id": channel_id,
            "user_id": user_id,
            "keys": keys,
        },
    )


async def handle_sync_remove(
    client: WebClient,
    channel_id: str,
    user_id: str,
    key: str,
    response_url: str,
) -> None:
    """Handle 'Remove from tracking' button click.

    Unregister the key from registry.
    Update original message.

    Args:
        client: Slack WebClient
        channel_id: Slack channel ID
        user_id: User who clicked
        key: Jira issue key to remove
        response_url: Response URL for updating original message
    """
    from src.db import get_connection
    from src.db.jira_registry import JiraRegistryStore

    try:
        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)
            removed = await registry.unregister(channel_id, key)

        if removed:
            logger.info(
                "Removed issue from tracking",
                extra={
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "key": key,
                },
            )
            result_text = f":white_check_mark: Removed {key} from tracking"
        else:
            result_text = f":warning: {key} was not tracked"

        # Update via response_url
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                response_url,
                json={
                    "replace_original": True,
                    "text": result_text,
                    "blocks": [{
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": result_text,
                        }
                    }],
                },
            )

    except Exception as e:
        logger.error(f"Failed to remove issue: {e}", exc_info=True)
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                response_url,
                json={
                    "replace_original": False,
                    "text": f":x: Failed to remove {key}: {str(e)}",
                },
            )


def handle_sync_track_all_button(ack, body, client):
    """Handle sync_track_all button click (Bolt handler)."""
    ack()

    import asyncio

    action = body["actions"][0]
    data = json.loads(action["value"])
    channel_id = data.get("channel_id")
    keys = data.get("keys", [])
    response_url = body.get("response_url", "")
    user_id = body.get("user", {}).get("id", "unknown")

    asyncio.create_task(
        handle_sync_track_all(client, channel_id, user_id, keys, response_url)
    )


def handle_sync_remove_button(ack, body, client):
    """Handle sync_remove button click (Bolt handler)."""
    ack()

    import asyncio

    action = body["actions"][0]
    data = json.loads(action["value"])
    channel_id = data.get("channel_id")
    key = data.get("key")
    response_url = body.get("response_url", "")
    user_id = body.get("user", {}).get("id", "unknown")

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
