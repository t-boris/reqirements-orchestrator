"""Slack blocks for multi-ticket preview and confirmation.

Supports Epic + linked stories workflow with safety latches.
"""
from typing import Any


def build_quantity_confirm_blocks(item_count: int) -> list[dict]:
    """Build confirmation dialog for >3 items.

    Triggered when user requests more than MULTI_TICKET_QUANTITY_THRESHOLD items.

    Args:
        item_count: Total number of items to be created

    Returns:
        Slack blocks with confirmation prompt and buttons
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"You're about to create *{item_count} items*. This includes 1 Epic and {item_count - 1} linked stories.\n\nWould you like to proceed?",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"Yes, create {item_count} items"},
                    "action_id": "multi_ticket_confirm_quantity",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "multi_ticket_cancel",
                },
            ],
        },
    ]


def build_size_confirm_blocks(total_chars: int) -> list[dict]:
    """Build confirmation for large batch.

    Triggered when total content exceeds MULTI_TICKET_SIZE_THRESHOLD chars.

    Args:
        total_chars: Total character count of all items

    Returns:
        Slack blocks with size warning and batch options
    """
    kb = total_chars // 1024
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"This is a large batch (~{kb}KB of content).\n\nWould you like to:\n\u2022 *Create all at once* - Everything in one batch\n\u2022 *Split into batches* - Create Epic first, then stories in groups",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Create all at once"},
                    "action_id": "multi_ticket_create_all",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Split into batches"},
                    "action_id": "multi_ticket_split",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "multi_ticket_cancel",
                },
            ],
        },
    ]


def build_multi_ticket_preview_blocks(
    items: list[dict[str, Any]],
    ui_version: int = 0,
) -> list[dict]:
    """Build preview blocks for all items in multi-ticket batch.

    Shows each item (epic and stories) with Edit buttons.
    Epic displayed first with book emoji, stories with page emoji.

    Args:
        items: List of MultiTicketItem dicts with id, type, title, description, parent_id
        ui_version: Version for stale button detection

    Returns:
        Slack blocks for full preview with edit and approve buttons
    """
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Multi-Ticket Preview ({len(items)} items)",
            },
        },
    ]

    for item in items:
        emoji = "book" if item["type"] == "epic" else "page_facing_up"
        item_type = item["type"].title()
        description = item.get("description", "")
        truncated_desc = description[:100] + "..." if len(description) > 100 else description

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":{emoji}: *{item_type}*: {item['title']}\n_{truncated_desc}_",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": f"multi_ticket_edit_story:{item['id']}:{ui_version}",
            },
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Create All in Jira"},
                "action_id": f"multi_ticket_approve:{ui_version}",
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Cancel"},
                "action_id": "multi_ticket_cancel",
            },
        ],
    })

    return blocks
