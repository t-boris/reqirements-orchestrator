"""Status card blocks for channel-level visibility.

Provides Slack block builders for Jira and WorkItem status cards.
These are posted to the CHANNEL (not thread) to ensure Jira links
are visible at the channel level, not buried in threads.

Key behaviors:
- Posted to channel for visibility (R22)
- Discussion stays in threads
- Compact format with key info
- Links to Jira and thread

Phase 27.6 - Notifications & Slack UX
"""
from typing import Any, Optional


def build_jira_status_card(
    jira_key: str,
    jira_url: str,
    summary: str,
    status: str,
    assignee: Optional[str] = None,
    issue_type: str = "Task",
) -> list[dict[str, Any]]:
    """Build a Jira status card for channel-level visibility.

    Posted to channel (not thread) for official status.
    Provides quick overview with link to Jira for details.

    Args:
        jira_key: Jira issue key (e.g., SCRUM-123)
        jira_url: Full URL to the Jira issue
        summary: Issue title/summary
        status: Current Jira status (To Do, In Progress, Done, etc.)
        assignee: Optional assignee username (not Slack user ID)
        issue_type: Jira issue type (Epic, Story, Bug, Task, Spike)

    Returns:
        List of Slack blocks for the status card
    """
    # Status emoji mapping
    status_emoji = {
        "To Do": ":white_circle:",
        "Open": ":white_circle:",
        "Backlog": ":white_circle:",
        "In Progress": ":large_blue_circle:",
        "In Development": ":large_blue_circle:",
        "In Review": ":purple_circle:",
        "Review": ":purple_circle:",
        "Done": ":white_check_mark:",
        "Closed": ":checkered_flag:",
        "Resolved": ":white_check_mark:",
    }.get(status, ":white_circle:")

    # Issue type emoji
    type_emoji = {
        "Epic": ":zap:",
        "Story": ":bookmark:",
        "Bug": ":bug:",
        "Task": ":ballot_box_with_check:",
        "Spike": ":mag:",
        "Sub-task": ":pushpin:",
    }.get(issue_type, ":ballot_box_with_check:")

    assignee_text = f" | Assignee: {assignee}" if assignee else ""

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{type_emoji} *<{jira_url}|{jira_key}>*: {summary}"
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "View in Jira", "emoji": True},
                "url": jira_url,
                "action_id": "view_jira_link"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"{status_emoji} {status}{assignee_text}"
                }
            ]
        }
    ]

    return blocks


def build_workitem_status_card(
    workitem_id: str,
    summary: str,
    status: str,
    jira_key: Optional[str] = None,
    jira_url: Optional[str] = None,
    owners: Optional[list[str]] = None,
    thread_link: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Build a WorkItem status card for channel visibility.

    Used for draft announcements and status updates before Jira sync.

    Args:
        workitem_id: WorkItem UUID (for internal reference)
        summary: Item title/summary
        status: WorkItem status (draft, active, done)
        jira_key: Optional Jira key if synced
        jira_url: Optional Jira URL if synced
        owners: Optional list of Slack user IDs who own this item
        thread_link: Optional permalink to the discussion thread

    Returns:
        List of Slack blocks for the status card
    """
    status_emoji = {
        "draft": ":pencil:",
        "active": ":construction:",
        "done": ":white_check_mark:",
    }.get(status, ":pencil:")

    # Build title with Jira link if available
    if jira_key and jira_url:
        title = f"*<{jira_url}|{jira_key}>*: {summary}"
    else:
        title = f"*{summary}*"

    # Build owners text (max 2 to prevent clutter)
    owners_text = ""
    if owners:
        owner_mentions = ", ".join(f"<@{o}>" for o in owners[:2])
        owners_text = f" | Owners: {owner_mentions}"
        if len(owners) > 2:
            owners_text += f" +{len(owners) - 2}"

    # Context elements
    context_text = f"{status_emoji} {status.title()}{owners_text}"

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": title}
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": context_text}
            ]
        }
    ]

    # Add thread link if available
    if thread_link:
        blocks[-1]["elements"].append({
            "type": "mrkdwn",
            "text": f" | <{thread_link}|View discussion>"
        })

    return blocks


def build_ticket_created_card(
    jira_key: str,
    jira_url: str,
    summary: str,
    created_by: str,
    thread_link: Optional[str] = None,
    issue_type: str = "Task",
) -> list[dict[str, Any]]:
    """Build a card announcing ticket creation.

    Posted to main channel (not thread) when a Jira ticket is created.
    Provides visibility that a new ticket exists.

    Args:
        jira_key: Jira issue key (e.g., SCRUM-123)
        jira_url: Full URL to the Jira issue
        summary: Issue title/summary
        created_by: Slack user ID who created the ticket
        thread_link: Optional permalink to the discussion thread
        issue_type: Jira issue type (Epic, Story, Bug, Task, Spike)

    Returns:
        List of Slack blocks for the creation announcement
    """
    # Issue type emoji
    type_emoji = {
        "Epic": ":zap:",
        "Story": ":bookmark:",
        "Bug": ":bug:",
        "Task": ":ballot_box_with_check:",
        "Spike": ":mag:",
        "Sub-task": ":pushpin:",
    }.get(issue_type, ":ballot_box_with_check:")

    # Build context with creator and optional thread link
    context_parts = [f"Created by <@{created_by}>"]
    if thread_link:
        context_parts.append(f"<{thread_link}|View discussion>")

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: {type_emoji} *<{jira_url}|{jira_key}>*: {summary}"
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "View in Jira", "emoji": True},
                "url": jira_url,
                "action_id": "view_jira_link"
            }
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": " | ".join(context_parts)}
            ]
        }
    ]

    return blocks


def build_status_update_card(
    jira_key: str,
    jira_url: str,
    summary: str,
    old_status: str,
    new_status: str,
    updated_by: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Build a card announcing status change.

    Posted to channel when a tracked ticket's status changes.

    Args:
        jira_key: Jira issue key
        jira_url: Full URL to the Jira issue
        summary: Issue title/summary
        old_status: Previous status
        new_status: New status
        updated_by: Optional Slack user ID who made the change

    Returns:
        List of Slack blocks for the status update
    """
    # Status emojis
    old_emoji = _get_status_emoji(old_status)
    new_emoji = _get_status_emoji(new_status)

    # Build context
    context_parts = [f"{old_emoji} {old_status} → {new_emoji} {new_status}"]
    if updated_by:
        context_parts.append(f"Updated by <@{updated_by}>")

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":arrows_counterclockwise: *<{jira_url}|{jira_key}>*: {summary}"
            }
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": " | ".join(context_parts)}
            ]
        }
    ]

    return blocks


def _get_status_emoji(status: str) -> str:
    """Get emoji for a Jira status."""
    return {
        "To Do": ":white_circle:",
        "Open": ":white_circle:",
        "Backlog": ":white_circle:",
        "In Progress": ":large_blue_circle:",
        "In Development": ":large_blue_circle:",
        "In Review": ":purple_circle:",
        "Review": ":purple_circle:",
        "Done": ":white_check_mark:",
        "Closed": ":checkered_flag:",
        "Resolved": ":white_check_mark:",
    }.get(status, ":white_circle:")
