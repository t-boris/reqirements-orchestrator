"""Slack blocks for commit preview and approval (Phase 23.3).

Shows what will be committed to channel truth with explicit approval button.
"""
import json
from typing import Any


def build_commit_preview_blocks(
    commit_type: str,
    summary: str,
    details: list[str],
    channel_id: str,
    thread_ts: str | None,
    user_id: str,
    *,
    workitem_id: str | None = None,
    extra_data: dict[str, Any] | None = None,
) -> list[dict]:
    """Build Slack blocks for commit preview with approval button.

    Format:
    *Draft ready*

    Summary (what will be committed):
    - Decision: Use background worker + idempotency key
    - Work items: EPIC PROJ-50 updated, STORY draft created

    [Approve & Commit] [Edit] [Not now]

    Args:
        commit_type: Type of commit (decision, workitem_created, etc.)
        summary: One-line summary of the commit
        details: List of bullet points describing what's included
        channel_id: Channel ID for the commit
        thread_ts: Source thread timestamp (if any)
        user_id: User who will be committing
        workitem_id: Related WorkItem UUID (if any)
        extra_data: Additional data to pass to handlers

    Returns:
        List of Slack block dicts for commit preview
    """
    # Format type for display
    type_display = _format_commit_type(commit_type)

    # Build details text
    details_text = "\n".join(f"• {detail}" for detail in details) if details else f"• {summary}"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":memo: *Draft ready*\n\n*{type_display}*"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Summary (what will be committed):*\n{details_text}"
            }
        },
    ]

    # Build button value with all context
    button_value = json.dumps({
        "commit_type": commit_type,
        "summary": summary[:500],  # Truncate for Slack limits
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "user_id": user_id,
        "workitem_id": workitem_id,
        **(extra_data or {}),
    })

    # Action buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve & Commit", "emoji": True},
                "style": "primary",
                "action_id": "approve_commit",
                "value": button_value,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": "edit_commit",
                "value": button_value,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Not now"},
                "action_id": "dismiss_commit",
                "value": button_value,
            },
        ]
    })

    return blocks


def build_commit_success_blocks(
    commit_type: str,
    summary: str,
    committed_by: str,
    thread_ts: str | None,
    channel_id: str,
) -> list[dict]:
    """Build blocks shown after successful commit.

    Format:
    :white_check_mark: Committed
    Decision: Use background worker
    _Committed by @user - View thread_

    Args:
        commit_type: Type of commit
        summary: Commit summary
        committed_by: User ID who committed
        thread_ts: Thread timestamp for link
        channel_id: Channel ID for link

    Returns:
        List of Slack block dicts for success message
    """
    type_display = _format_commit_type(commit_type)

    # Build thread link if available
    thread_link = ""
    if thread_ts and channel_id:
        link_url = f"https://slack.com/archives/{channel_id}/p{thread_ts.replace('.', '')}"
        thread_link = f" - <{link_url}|View thread>"

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: *Committed*\n\n*{type_display}:* {summary}"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Committed by <@{committed_by}>{thread_link}"
                }
            ]
        },
    ]


def _format_commit_type(commit_type: str) -> str:
    """Format commit type for display."""
    type_map = {
        "decision": "Decision",
        "workitem_created": "Work Item Created",
        "workitem_updated": "Work Item Updated",
        "constraint_added": "Constraint Added",
        "jira_synced": "Synced to Jira",
    }
    return type_map.get(commit_type, commit_type.replace("_", " ").title())
