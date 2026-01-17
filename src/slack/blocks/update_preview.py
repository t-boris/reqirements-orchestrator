"""Slack blocks for ticket update preview with confirmation flow.

Shows proposed changes before applying to Jira, allowing user to
review, edit, or cancel the update.
"""

import json
from typing import Optional


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate text with ellipsis if too long."""
    if not text:
        return "_empty_"
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def build_update_preview_blocks(
    ticket_key: str,
    ticket_url: str,
    current_description: str,
    proposed_content: str,
    update_mode: str = "append",
    ui_version: int = 0,
) -> list[dict]:
    """Build preview blocks for ticket update with Apply/Edit/Cancel buttons.

    Args:
        ticket_key: Jira ticket key (e.g., "SCRUM-136")
        ticket_url: Full URL to the Jira ticket
        current_description: Current ticket description
        proposed_content: Content to add/replace
        update_mode: "append" or "replace"
        ui_version: Version number for stale button detection

    Returns:
        List of Slack block dicts
    """
    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Proposed Update to {ticket_key}",
            "emoji": True
        }
    })

    # Current description section
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Current description:*\n```{_truncate(current_description, 800)}```"
        }
    })

    blocks.append({"type": "divider"})

    # Proposed changes
    mode_label = "Content to append" if update_mode == "append" else "New description"
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{mode_label}:*\n```{_truncate(proposed_content, 1000)}```"
        }
    })

    # Mode indicator
    if update_mode == "append":
        mode_text = "This content will be *appended* to the existing description."
    else:
        mode_text = "This will *replace* the existing description."

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": mode_text
        }]
    })

    blocks.append({"type": "divider"})

    # Store data for handlers
    button_data = json.dumps({
        "key": ticket_key,
        "mode": update_mode,
    })

    # Action buttons
    version_suffix = f":{ui_version}" if ui_version > 0 else ""
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Apply Changes"},
                "action_id": f"update_preview_apply{version_suffix}",
                "value": button_data,
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": f"update_preview_edit{version_suffix}",
                "value": button_data,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Cancel"},
                "action_id": f"update_preview_cancel{version_suffix}",
                "value": button_data,
            },
        ]
    })

    # Link to ticket
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"<{ticket_url}|View {ticket_key} in Jira>"
        }]
    })

    return blocks


def build_update_edit_modal(
    ticket_key: str,
    current_description: str,
    proposed_content: str,
    update_mode: str = "append",
) -> dict:
    """Build modal for editing update content before applying.

    Args:
        ticket_key: Jira ticket key
        current_description: Current ticket description (for reference)
        proposed_content: Proposed content to edit
        update_mode: "append" or "replace"

    Returns:
        Slack modal view dict
    """
    return {
        "type": "modal",
        "callback_id": "update_edit_modal",
        "title": {
            "type": "plain_text",
            "text": f"Edit Update: {ticket_key}"
        },
        "submit": {
            "type": "plain_text",
            "text": "Apply Changes"
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel"
        },
        "private_metadata": json.dumps({
            "ticket_key": ticket_key,
            "update_mode": update_mode,
        }),
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Current description of {ticket_key}:*\n```{_truncate(current_description, 500)}```"
                }
            },
            {"type": "divider"},
            {
                "type": "input",
                "block_id": "update_content_block",
                "label": {
                    "type": "plain_text",
                    "text": "Content to add" if update_mode == "append" else "New description"
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "update_content_input",
                    "multiline": True,
                    "initial_value": proposed_content,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Edit the content that will be added to the ticket..."
                    }
                }
            },
            {
                "type": "input",
                "block_id": "update_mode_block",
                "label": {
                    "type": "plain_text",
                    "text": "Update mode"
                },
                "element": {
                    "type": "static_select",
                    "action_id": "update_mode_select",
                    "initial_option": {
                        "text": {"type": "plain_text", "text": "Append to existing"},
                        "value": "append"
                    } if update_mode == "append" else {
                        "text": {"type": "plain_text", "text": "Replace existing"},
                        "value": "replace"
                    },
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": "Append to existing"},
                            "value": "append"
                        },
                        {
                            "text": {"type": "plain_text", "text": "Replace existing"},
                            "value": "replace"
                        }
                    ]
                }
            }
        ]
    }


def build_update_success_blocks(
    ticket_key: str,
    ticket_url: str,
    update_summary: str,
) -> list[dict]:
    """Build success message blocks after update is applied.

    Args:
        ticket_key: Jira ticket key
        ticket_url: Full URL to the ticket
        update_summary: Brief summary of what was changed

    Returns:
        List of Slack block dicts
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: *{ticket_key}* updated successfully\n\n{update_summary}"
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "View in Jira"},
                "url": ticket_url,
            }
        }
    ]
