"""
Block Kit Formatter - Slack message formatting utilities.

Provides functions to format responses, drafts, conflicts, and errors
using Slack Block Kit for rich message display.
"""

from typing import Any


SLACK_TEXT_LIMIT = 2900  # Slack limit is 3000, leave margin for safety


def _split_text_to_blocks(text: str, limit: int = SLACK_TEXT_LIMIT) -> list[dict]:
    """
    Split long text into multiple section blocks.

    Args:
        text: Text to split.
        limit: Max characters per block.

    Returns:
        List of section blocks.
    """
    if len(text) <= limit:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    blocks = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": remaining}})
            break

        # Find a good break point (newline or space)
        break_point = remaining.rfind("\n", 0, limit)
        if break_point == -1 or break_point < limit // 2:
            break_point = remaining.rfind(" ", 0, limit)
        if break_point == -1 or break_point < limit // 2:
            break_point = limit

        chunk = remaining[:break_point].rstrip()
        remaining = remaining[break_point:].lstrip()

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})

    return blocks


def format_response(
    response: str,
    draft: dict[str, Any] | None = None,
    jira_key: str | None = None,
) -> list[dict]:
    """
    Format a standard response with optional draft and Jira link.

    Args:
        response: Main response text.
        draft: Optional requirement draft.
        jira_key: Optional Jira issue key.

    Returns:
        Block Kit blocks.
    """
    # Split long responses into multiple blocks
    blocks = _split_text_to_blocks(response)

    # Add Jira link if available
    if jira_key:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Jira: `{jira_key}`",
                },
            ],
        })

    # Add draft summary if available
    if draft:
        blocks.append({"type": "divider"})
        blocks.extend(format_draft_summary(draft))

    return blocks


def format_draft_preview(draft: dict[str, Any]) -> list[dict]:
    """
    Format a detailed draft preview for approval.

    Args:
        draft: Requirement draft dictionary.

    Returns:
        Block Kit blocks.
    """
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{draft.get('title', 'Untitled')}*",
            },
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Type:* {draft.get('issue_type', 'Story')}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Priority:* {draft.get('priority', 'Medium')}",
                },
            ],
        },
    ]

    # Add description
    description = draft.get("description", "")
    if description:
        # Truncate long descriptions
        if len(description) > 500:
            description = description[:497] + "..."

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Description:*\n{description}"},
        })

    # Add acceptance criteria
    criteria = draft.get("acceptance_criteria", [])
    if criteria:
        criteria_text = "\n".join(f"- {c}" for c in criteria[:5])
        if len(criteria) > 5:
            criteria_text += f"\n_...and {len(criteria) - 5} more_"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Acceptance Criteria:*\n{criteria_text}"},
        })

    # Add labels
    labels = draft.get("labels", [])
    if labels:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Labels: {', '.join(f'`{l}`' for l in labels)}"},
            ],
        })

    return blocks


def format_draft_summary(draft: dict[str, Any]) -> list[dict]:
    """
    Format a compact draft summary.

    Args:
        draft: Requirement draft dictionary.

    Returns:
        Block Kit blocks.
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Draft:* {draft.get('title', 'Untitled')} ({draft.get('issue_type', 'Story')})",
            },
        },
    ]


def format_conflicts(conflicts: list[dict[str, Any]]) -> list[dict]:
    """
    Format conflict warnings.

    Args:
        conflicts: List of conflict dictionaries.

    Returns:
        Block Kit blocks.
    """
    if not conflicts:
        return []

    blocks = [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Potential Conflicts Detected*",
            },
        },
    ]

    for conflict in conflicts[:3]:  # Limit to 3 conflicts
        emoji = _get_conflict_emoji(conflict.get("conflict_type", ""))
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{emoji} *{conflict.get('conflict_type', 'Unknown').title()}* with "
                    f"`{conflict.get('existing_id', 'Unknown')}`\n"
                    f"{conflict.get('description', '')}"
                ),
            },
        })

    if len(conflicts) > 3:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"_...and {len(conflicts) - 3} more conflicts_"},
            ],
        })

    return blocks


def _get_conflict_emoji(conflict_type: str) -> str:
    """Get emoji for conflict type."""
    emojis = {
        "contradiction": ":warning:",
        "duplicate": ":x:",
        "overlap": ":thought_balloon:",
    }
    return emojis.get(conflict_type.lower(), ":grey_question:")


def format_error(error: str) -> list[dict]:
    """
    Format an error message.

    Args:
        error: Error message text.

    Returns:
        Block Kit blocks.
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":x: *Error*\n{error}",
            },
        },
    ]


def format_status(state: dict[str, Any]) -> list[dict]:
    """
    Format graph state for status display.

    Args:
        state: Current graph state.

    Returns:
        Block Kit blocks.
    """
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Channel Status"},
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Intent:* `{state.get('intent', 'unknown')}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Confidence:* `{state.get('intent_confidence', 0):.0%}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Persona:* `{state.get('active_persona') or 'Main Bot'}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Awaiting:* `{'Yes' if state.get('awaiting_human') else 'No'}`",
                },
            ],
        },
    ]

    if state.get("draft"):
        blocks.append({"type": "divider"})
        blocks.extend(format_draft_summary(state["draft"]))

    if state.get("jira_issue_key"):
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Last Jira Issue: `{state['jira_issue_key']}`"},
            ],
        })

    return blocks


def format_approval_list(approvals: list[dict[str, Any]]) -> list[dict]:
    """
    Format permanent approvals list.

    Args:
        approvals: List of approval records.

    Returns:
        Block Kit blocks.
    """
    if not approvals:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_No permanent approvals configured_"},
            },
        ]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Permanent Approvals"},
        },
    ]

    for i, approval in enumerate(approvals, 1):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{i}.* `{approval.get('pattern', 'Any')}`\n"
                    f"Created by <@{approval.get('user_id', 'Unknown')}>"
                ),
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Delete"},
                "style": "danger",
                "action_id": f"delete_approval_{i}",
                "value": str(i),
            },
        })

    return blocks


def format_help() -> list[dict]:
    """
    Format help message.

    Returns:
        Block Kit blocks.
    """
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "MARO - Requirements Bot"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "I help capture and manage requirements in Jira.\n\n"
                    "*How to use:*\n"
                    "- Just describe your requirement in natural language\n"
                    "- @mention me if you want a guaranteed response\n"
                    "- I'll draft a Jira issue and ask for your approval\n\n"
                    "*Commands:*\n"
                    "- `/req-status` - Show current state\n"
                    "- `/req-config` - Configure channel settings\n"
                    "- `/req-clean` - Clear memory and state\n"
                    "- `/req-approve list` - List permanent approvals\n"
                    "- `/req-approve delete <id>` - Remove an approval"
                ),
            },
        },
    ]
