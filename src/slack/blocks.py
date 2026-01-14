"""Slack Block Kit builders for rich messages."""

from typing import Optional


def build_session_card(
    epic_key: Optional[str],
    epic_summary: Optional[str],
    session_status: str,
    thread_ts: str,
) -> list[dict]:
    """Build Session Card blocks for thread header.

    Shows: Epic link, session status, available commands.
    """
    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Session Active",
            "emoji": True
        }
    })

    # Epic info section
    if epic_key:
        epic_text = f"*Epic:* <https://jira.example.com/browse/{epic_key}|{epic_key}>"
        if epic_summary:
            epic_text += f" - {epic_summary}"
    else:
        epic_text = "*Epic:* _Not linked yet_"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": epic_text
        }
    })

    # Status
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Status:* {session_status}"
        }
    })

    # Commands
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "Commands: `/jira status` | `/jira create` | @mention me"
        }]
    })

    return blocks


def build_epic_selector(
    suggested_epics: list[dict],
    message_preview: str,
) -> list[dict]:
    """Build Epic selection blocks.

    Args:
        suggested_epics: List of {key, summary, score} dicts
        message_preview: First part of user's message for context
    """
    blocks = []

    # Context
    preview_text = message_preview[:100]
    if len(message_preview) > 100:
        preview_text += "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"I see you're discussing: _{preview_text}_\n\nWhich Epic does this relate to?"
        }
    })

    # Suggested epics as buttons
    if suggested_epics:
        buttons = []
        for epic in suggested_epics[:3]:  # Max 3 suggestions
            # Truncate summary for button text (max 75 chars total)
            button_text = f"{epic['key']}: {epic['summary'][:30]}"
            if len(epic['summary']) > 30:
                button_text += "..."

            buttons.append({
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": button_text[:75],  # Slack limit
                    "emoji": True
                },
                "value": epic["key"],
                "action_id": f"select_epic_{epic['key']}"
            })

        # Add "New Epic" option
        buttons.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "New Epic",
                "emoji": True
            },
            "value": "new",
            "action_id": "select_epic_new",
            "style": "primary"
        })

        blocks.append({
            "type": "actions",
            "elements": buttons
        })
    else:
        # No suggestions, just show "New Epic"
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Create New Epic",
                    "emoji": True
                },
                "value": "new",
                "action_id": "select_epic_new",
                "style": "primary"
            }]
        })

    return blocks
