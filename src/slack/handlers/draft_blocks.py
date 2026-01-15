"""Block builders for draft preview states.

Helper functions for building Slack blocks for draft preview messages
in various states (created, approved, rejected).
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from slack_sdk.web import WebClient

if TYPE_CHECKING:
    from src.schemas.draft import TicketDraft

logger = logging.getLogger(__name__)


async def post_error_actions(
    client: WebClient,
    channel: str,
    thread_ts: str,
    session_id: str,
    draft_hash: str,
    error_msg: str,
) -> None:
    """Post error message with action buttons after Jira creation failure.

    Shows factual error message and offers user action options:
    - Retry: Try creating the ticket again
    - Skip Jira: Continue without Jira (session still has draft)
    - Cancel: Abort the operation

    Args:
        client: Slack WebClient for posting message
        channel: Channel ID to post in
        thread_ts: Thread timestamp
        session_id: Session ID for button values
        draft_hash: Draft hash for button values
        error_msg: Error message to display
    """
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":x: Could not create ticket: {error_msg}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Retry", "emoji": True},
                    "style": "primary",
                    "action_id": "retry_jira_create",
                    "value": f"{session_id}:{draft_hash}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Skip Jira", "emoji": True},
                    "action_id": "skip_jira_create",
                    "value": f"{session_id}:{draft_hash}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "style": "danger",
                    "action_id": "cancel_jira_create",
                    "value": f"{session_id}:{draft_hash}",
                },
            ],
        },
    ]

    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Could not create ticket: {error_msg}",
        blocks=blocks,
    )


def update_preview_to_created(
    client: WebClient,
    channel: str,
    message_ts: str,
    draft: "TicketDraft",
    jira_key: str,
    jira_url: str,
    created_by: str,
) -> None:
    """Update preview message to show created state with Jira link.

    Updates the original preview message to:
    - Show "Ticket Created" header with Jira key
    - Display ticket details (title, problem, etc.)
    - Remove approval buttons
    - Add context: Created by @user with Jira link

    Args:
        client: Slack WebClient
        channel: Channel ID
        message_ts: Preview message timestamp to update
        draft: TicketDraft that was created
        jira_key: Created Jira issue key (e.g., PROJ-123)
        jira_url: URL to the Jira issue
        created_by: User ID who created the ticket
    """
    blocks = []

    # Header with created status and Jira key
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Ticket Created: {jira_key}",
            "emoji": True
        }
    })

    # Title with Jira link
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*<{jira_url}|{draft.title or 'Untitled'}>*"
        }
    })

    # Problem (abbreviated for created state)
    problem_preview = draft.problem[:200] if draft.problem else "_Not set_"
    if draft.problem and len(draft.problem) > 200:
        problem_preview += "..."
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Problem:*\n{problem_preview}"
        }
    })

    # Acceptance Criteria count
    if draft.acceptance_criteria:
        ac_count = len(draft.acceptance_criteria)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Acceptance Criteria:* {ac_count} item{'s' if ac_count != 1 else ''}"
            }
        })

    # Divider
    blocks.append({"type": "divider"})

    # Context with Jira link and creator
    created_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Created by <@{created_by}> at {created_time} | <{jira_url}|View in Jira>"
            }
        ]
    })

    try:
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text=f"Ticket created: {jira_key}",
            blocks=blocks,
        )
    except Exception as e:
        logger.warning(f"Failed to update preview to created state: {e}")


def build_approved_preview_blocks(draft: "TicketDraft", approved_by: str) -> list[dict]:
    """Build preview blocks with approval status (no action buttons).

    Used to update the preview message after approval.
    """
    blocks = []

    # Header with approved status
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Ticket Approved",
            "emoji": True
        }
    })

    # Title
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Title:* {draft.title or '_Not set_'}"
        }
    })

    # Problem
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Problem:*\n{draft.problem or '_Not set_'}"
        }
    })

    # Solution (if present)
    if draft.proposed_solution:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Solution:*\n{draft.proposed_solution}"
            }
        })

    # Acceptance Criteria
    if draft.acceptance_criteria:
        ac_text = "*Acceptance Criteria:*\n"
        for i, ac in enumerate(draft.acceptance_criteria, 1):
            ac_text += f"{i}. {ac}\n"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ac_text
            }
        })

    # Divider
    blocks.append({"type": "divider"})

    # Approval context (instead of buttons)
    approval_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Approved by <@{approved_by}> at {approval_time}"
        }]
    })

    return blocks


def build_rejected_preview_blocks(draft: "TicketDraft", rejected_by: str) -> list[dict]:
    """Build preview blocks with rejection status (no action buttons).

    Used to update the preview message after rejection.
    """
    blocks = []

    # Header with rejected status
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Changes Requested",
            "emoji": True
        }
    })

    # Title
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Title:* {draft.title or '_Not set_'}"
        }
    })

    # Problem (abbreviated)
    problem_preview = draft.problem[:100] if draft.problem else "_Not set_"
    if draft.problem and len(draft.problem) > 100:
        problem_preview += "..."
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Problem:* {problem_preview}"
        }
    })

    # Divider
    blocks.append({"type": "divider"})

    # Rejection context (instead of buttons)
    rejection_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Changes requested by <@{rejected_by}> at {rejection_time}"
        }]
    })

    return blocks
