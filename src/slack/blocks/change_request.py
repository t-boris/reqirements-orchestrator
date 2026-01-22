"""Slack blocks for change request preview UI."""

from typing import Any

from src.schemas.change_request import ChangePreview, ChangeRequest


def build_change_preview_blocks(
    preview: ChangePreview,
    request: ChangeRequest,
) -> list[dict[str, Any]]:
    """Build Slack blocks for change request preview.

    UI:
    +--------------------------------+
    | CHANGE REQUEST                 |
    |                                |
    | Target: SCRUM-123              |
    |                                |
    | Changes:                       |
    | - priority: Medium -> High     |
    | - summary: "Old" -> "New"      |
    | + labels: ["urgent"]           |
    |                                |
    | Warning: This will update Jira.|
    |                                |
    | [Approve] [Edit] [Cancel]      |
    +--------------------------------+
    """
    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": "Change Request", "emoji": True},
    })

    # Preview content
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": preview.preview_text},
    })

    # Warnings
    if preview.warnings:
        warning_text = "\n".join(f":warning: {w}" for w in preview.warnings)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": warning_text},
        })

    blocks.append({"type": "divider"})

    # Action buttons
    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Approve Changes"},
            "action_id": "change_request_approve",
            "style": "primary",
            "value": request.request_id,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Edit"},
            "action_id": "change_request_edit",
            "value": request.request_id,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Cancel"},
            "action_id": "change_request_cancel",
            "style": "danger",
            "value": request.request_id,
        },
    ]

    blocks.append({
        "type": "actions",
        "elements": buttons,
    })

    return blocks


def build_change_applied_blocks(
    request: ChangeRequest,
    jira_updated: bool = False,
) -> list[dict[str, Any]]:
    """Build confirmation blocks after change is applied."""
    text = ":white_check_mark: *Changes applied*\n"

    for target in request.targets:
        text += f"- Updated `{target.target_id}`\n"

    if jira_updated:
        text += "\n_Jira has been synced._"

    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        }
    ]
