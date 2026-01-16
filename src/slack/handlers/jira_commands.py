"""Jira command handlers for natural language Jira management.

Handles:
- jira_command_confirm: Show confirmation dialog before executing command
- jira_command_execute: Execute confirmed command
- jira_command_cancel: Cancel command
- jira_command_ambiguous: Handle ambiguous target selection
"""
import json
import logging
from typing import Any

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity

logger = logging.getLogger(__name__)


def build_jira_command_confirm_blocks(
    command_details: dict,
) -> list[dict[str, Any]]:
    """Build Slack blocks for command confirmation.

    Args:
        command_details: Command details from JiraCommandNode

    Returns:
        List of Slack block objects
    """
    target = command_details.get("target", "")
    command_type = command_details.get("command_type", "update")
    field = command_details.get("field", "")
    old_value = command_details.get("old_value")
    new_value = command_details.get("new_value", "")

    blocks = []

    if command_type == "delete":
        # Delete requires extra warning
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Delete {target}?*\n\nThis cannot be undone."
            }
        })
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Delete"},
                    "action_id": "jira_command_execute",
                    "value": json.dumps(command_details),
                    "style": "danger",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "jira_command_cancel",
                    "value": json.dumps({"target": target}),
                },
            ]
        })
    else:
        # Update - show before/after
        if old_value:
            change_text = f"Change *{field}* of *{target}* from `{old_value}` to `{new_value}`?"
        else:
            change_text = f"Change *{field}* of *{target}* to `{new_value}`?"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": change_text}
        })
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Confirm"},
                    "action_id": "jira_command_execute",
                    "value": json.dumps(command_details),
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "jira_command_cancel",
                    "value": json.dumps({"target": target}),
                },
            ]
        })

    return blocks


async def handle_jira_command_confirm(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle jira_command_confirm action from dispatch.

    Shows confirmation dialog with Confirm/Cancel buttons.

    Args:
        result: Decision result from JiraCommandNode
        identity: Session identity
        client: Slack WebClient
    """
    command_details = result.get("command_details", {})

    blocks = build_jira_command_confirm_blocks(command_details)

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f"Confirm change to {command_details.get('target', '')}?",
        blocks=blocks,
    )


async def handle_jira_command_ambiguous(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
) -> None:
    """Handle jira_command_ambiguous action from dispatch.

    Shows message asking user to specify which ticket.

    Args:
        result: Decision result from JiraCommandNode
        identity: Session identity
        client: Slack WebClient
    """
    message = result.get("message", "Which ticket?")
    options = result.get("options", [])

    if options:
        # Build option buttons
        elements = []
        for option in options[:5]:  # Max 5 buttons
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": option},
                "action_id": f"jira_command_select_{option}",
                "value": json.dumps({
                    "target": option,
                    "command_type": result.get("command_type"),
                    "command_field": result.get("command_field"),
                    "command_value": result.get("command_value"),
                }),
            })

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": message}},
            {"type": "actions", "elements": elements},
        ]

        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=message,
            blocks=blocks,
        )
    else:
        # No options - just ask
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=message,
        )


def handle_jira_command_execute(ack, body, client):
    """Handle jira_command_execute button click.

    Executes the confirmed Jira command.
    """
    ack()

    action = body["actions"][0]
    command_details = json.loads(action["value"])

    target = command_details.get("target", "")
    command_type = command_details.get("command_type", "update")
    field = command_details.get("field", "")
    new_value = command_details.get("new_value", "")

    channel_id = body["channel"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
    message_ts = body["message"]["ts"]

    # Import here to avoid circular imports
    import asyncio
    asyncio.create_task(_execute_jira_command(
        client=client,
        channel_id=channel_id,
        thread_ts=thread_ts,
        message_ts=message_ts,
        target=target,
        command_type=command_type,
        field=field,
        new_value=new_value,
    ))


async def _execute_jira_command(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    message_ts: str,
    target: str,
    command_type: str,
    field: str,
    new_value: str,
) -> None:
    """Execute Jira command after confirmation.

    Args:
        client: Slack WebClient
        channel_id: Channel ID
        thread_ts: Thread timestamp
        message_ts: Confirmation message timestamp (to update)
        target: Issue key
        command_type: update or delete
        field: Field to update
        new_value: New value for field
    """
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.graph.nodes.jira_command import normalize_field_value
    from src.slack.channel_tracker import trigger_board_refresh

    try:
        settings = get_settings()
        jira_service = JiraService(settings)

        if command_type == "delete":
            # Delete issue
            await jira_service._request("DELETE", f"/rest/api/3/issue/{target}")

            # Update confirmation message
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f":white_check_mark: Deleted *{target}*",
                blocks=[{
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f":white_check_mark: Deleted *{target}*"}
                }],
            )

        else:
            # Update issue
            # Normalize value before sending to Jira
            normalized_value = await normalize_field_value(field, new_value, jira_service, target)

            # Build update payload based on field
            if field == "status":
                # Status changes need transition API
                await _transition_issue(jira_service, target, normalized_value)
            else:
                # Regular field update
                updates = _build_field_update(field, normalized_value)
                await jira_service.update_issue(target, updates)

            # Update confirmation message
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f":white_check_mark: Updated *{target}*: {field} -> {new_value}",
                blocks=[{
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f":white_check_mark: Updated *{target}*: {field} -> `{new_value}`"}
                }],
            )

        await jira_service.close()

        # Trigger board refresh
        await trigger_board_refresh(channel_id, settings.jira_url)

        logger.info(
            "Jira command executed",
            extra={
                "target": target,
                "command_type": command_type,
                "field": field,
                "new_value": new_value,
            }
        )

    except Exception as e:
        logger.error(f"Failed to execute Jira command: {e}", exc_info=True)

        # Update with error
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":x: Failed to update *{target}*: {str(e)}",
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":x: Failed to update *{target}*: {str(e)}"}
            }],
        )


async def _transition_issue(jira_service, issue_key: str, target_status: str) -> None:
    """Transition an issue to a new status.

    Args:
        jira_service: JiraService instance
        issue_key: Issue key
        target_status: Target status name
    """
    # Get available transitions
    response = await jira_service._request(
        "GET",
        f"/rest/api/3/issue/{issue_key}/transitions",
    )

    transitions = response.get("transitions", [])

    # Find matching transition
    transition_id = None
    target_lower = target_status.lower().replace(" ", "")

    for t in transitions:
        name = t.get("name", "")
        to_status = t.get("to", {}).get("name", "")

        if name.lower().replace(" ", "") == target_lower or to_status.lower().replace(" ", "") == target_lower:
            transition_id = t.get("id")
            break

    if not transition_id:
        available = [t.get("name") for t in transitions]
        raise ValueError(f"Status '{target_status}' not available. Available transitions: {', '.join(available)}")

    # Execute transition
    await jira_service._request(
        "POST",
        f"/rest/api/3/issue/{issue_key}/transitions",
        json_data={"transition": {"id": transition_id}},
    )


def _build_field_update(field: str, value: str) -> dict:
    """Build Jira field update payload.

    Args:
        field: Field name
        value: Normalized value

    Returns:
        Update payload for JiraService.update_issue
    """
    if field == "priority":
        return {"priority": {"name": value}}
    elif field == "assignee":
        # Value should be accountId
        return {"assignee": {"accountId": value}}
    elif field == "labels":
        # Value should be comma-separated labels
        labels = [l.strip() for l in value.split(",")]
        return {"labels": labels}
    elif field == "summary":
        return {"summary": value}
    elif field == "description":
        return {"description": value}
    else:
        # Generic field update
        return {field: value}


def handle_jira_command_cancel(ack, body, client):
    """Handle jira_command_cancel button click.

    Cancels the command and acknowledges.
    """
    ack()

    action = body["actions"][0]
    details = json.loads(action["value"])
    target = details.get("target", "")

    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    # Update message to show cancelled
    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text="Cancelled",
        blocks=[{
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"~Change to {target}~ Cancelled"}
        }],
    )


def handle_jira_command_select(ack, body, client):
    """Handle jira_command_select_* button click.

    User selected a specific ticket from ambiguous options.
    Shows confirmation dialog for the selected ticket.
    """
    ack()

    action = body["actions"][0]
    details = json.loads(action["value"])

    target = details.get("target", "")
    command_type = details.get("command_type", "update")
    command_field = details.get("command_field", "")
    command_value = details.get("command_value", "")

    channel_id = body["channel"]["id"]
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
    message_ts = body["message"]["ts"]

    # Build confirmation for selected ticket
    command_details = {
        "target": target,
        "command_type": command_type,
        "field": command_field,
        "new_value": command_value,
        "old_value": None,  # Would need to fetch
    }

    blocks = build_jira_command_confirm_blocks(command_details)

    # Update the original message with confirmation
    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Confirm change to {target}?",
        blocks=blocks,
    )
