"""WorkItem anchor blocks for Slack UI.

Phase 33: Anchor Message Architecture.

The anchor message is the canonical representation of the WorkItem.
All discussion happens in the thread under this message.
When WorkItem changes, the anchor message is UPDATED (not new message).

Format follows Decision anchor pattern:
- Type emoji + ID + title
- Status indicator
- Action buttons
"""
import json
from typing import Optional

from src.db.models import WorkItem, WorkItemStatus, WorkItemType


def build_workitem_anchor_blocks(
    workitem: WorkItem,
    jira_key: Optional[str] = None,
) -> list[dict]:
    """Build blocks for WorkItem anchor message.

    The anchor message is the canonical representation of the WorkItem.
    Format follows Decision anchor pattern:
    - Type emoji + ID + title
    - Status indicator
    - Action buttons

    Args:
        workitem: The WorkItem entity.
        jira_key: Optional Jira key if synced.

    Returns:
        List of Slack blocks for the anchor message.
    """
    # Type emoji mapping
    type_emoji = _get_type_emoji(workitem.item_type)

    # Status emoji
    status_emoji = _get_status_emoji(workitem.status)

    # Build header
    title = workitem.summary
    key = jira_key or workitem.jira_key
    if key:
        header = f"{type_emoji} *{key}* — {title}"
    else:
        # Use short UUID for drafts without Jira key
        header = f"{type_emoji} *WI-{workitem.id[:8]}* — {title}"

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header},
        }
    ]

    # Status line with optional assignee
    status_text = f"{status_emoji} Status: {workitem.status.value.capitalize()}"
    if workitem.owners and len(workitem.owners) > 0:
        # Show first owner as primary assignee
        status_text += f" | Owner: <@{workitem.owners[0]}>"

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": status_text}],
    })

    # Add action buttons based on status
    buttons = _get_action_buttons(workitem)
    if buttons:
        blocks.append({
            "type": "actions",
            "elements": buttons,
        })

    return blocks


def build_workitem_draft_blocks(
    workitem: WorkItem,
) -> list[dict]:
    """Build compact blocks for WorkItem in DRAFT status.

    Lighter weight than anchor - used during initial discussion.

    Args:
        workitem: The WorkItem entity.

    Returns:
        List of Slack blocks.
    """
    type_emoji = _get_type_emoji(workitem.item_type)
    type_label = workitem.item_type.value.capitalize()

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{type_emoji} *Draft {type_label}:*\n{workitem.summary}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "action_id": "workitem_edit",
                    "value": json.dumps({
                        "workitem_id": workitem.id,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "workitem_approve",
                    "value": json.dumps({
                        "workitem_id": workitem.id,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Discard"},
                    "style": "danger",
                    "action_id": "workitem_discard",
                    "value": json.dumps({
                        "workitem_id": workitem.id,
                    }),
                },
            ],
        },
    ]

    return blocks


def build_workitem_approved_blocks(
    workitem: WorkItem,
) -> list[dict]:
    """Build blocks for approved WorkItem.

    Compact but authoritative - no longer conversational.

    Args:
        workitem: The WorkItem entity.

    Returns:
        List of Slack blocks.
    """
    type_emoji = _get_type_emoji(workitem.item_type)
    type_label = workitem.item_type.value.upper()
    key = workitem.jira_key or f"WI-{workitem.id[:8]}"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{type_emoji} *{key}* ({type_label}) — *Active*\n"
                    f"{workitem.summary}"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Update"},
                    "action_id": "workitem_update",
                    "value": json.dumps({
                        "workitem_id": workitem.id,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Mark Done"},
                    "action_id": "workitem_done",
                    "value": json.dumps({
                        "workitem_id": workitem.id,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View in Jira"},
                    "action_id": "workitem_view_jira",
                    "value": json.dumps({
                        "workitem_id": workitem.id,
                        "jira_key": workitem.jira_key,
                    }),
                },
            ],
        },
    ]

    return blocks


def _get_type_emoji(item_type: WorkItemType) -> str:
    """Get emoji for work item type."""
    return {
        WorkItemType.EPIC: ":large_purple_circle:",
        WorkItemType.STORY: ":large_blue_circle:",
        WorkItemType.TASK: ":white_circle:",
        WorkItemType.BUG: ":red_circle:",
        WorkItemType.SPIKE: ":large_orange_circle:",
    }.get(item_type, ":white_circle:")


def _get_status_emoji(status: WorkItemStatus) -> str:
    """Get emoji for work item status."""
    return {
        WorkItemStatus.DRAFT: ":pencil2:",
        WorkItemStatus.ACTIVE: ":white_check_mark:",
        WorkItemStatus.DONE: ":checkered_flag:",
    }.get(status, ":grey_question:")


def _get_action_buttons(workitem: WorkItem) -> list[dict]:
    """Get appropriate action buttons based on WorkItem status.

    Args:
        workitem: The WorkItem entity.

    Returns:
        List of Slack button elements.
    """
    if workitem.status == WorkItemStatus.DRAFT:
        return [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": "workitem_edit",
                "value": json.dumps({"workitem_id": workitem.id}),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "style": "primary",
                "action_id": "workitem_approve",
                "value": json.dumps({"workitem_id": workitem.id}),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Discard"},
                "style": "danger",
                "action_id": "workitem_discard",
                "value": json.dumps({"workitem_id": workitem.id}),
            },
        ]
    elif workitem.status == WorkItemStatus.ACTIVE:
        buttons = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Update"},
                "action_id": "workitem_update",
                "value": json.dumps({"workitem_id": workitem.id}),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Mark Done"},
                "action_id": "workitem_done",
                "value": json.dumps({"workitem_id": workitem.id}),
            },
        ]
        if workitem.jira_key:
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "View in Jira"},
                "action_id": "workitem_view_jira",
                "value": json.dumps({
                    "workitem_id": workitem.id,
                    "jira_key": workitem.jira_key,
                }),
            })
        return buttons
    elif workitem.status == WorkItemStatus.DONE:
        return [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Reopen"},
                "action_id": "workitem_reopen",
                "value": json.dumps({"workitem_id": workitem.id}),
            },
        ]
    return []
