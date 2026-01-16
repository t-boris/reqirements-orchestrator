"""Slack blocks for multi-ticket preview and confirmation.

Supports Epic + linked stories workflow with safety latches.
"""
from typing import Any, Optional


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
    source_persona: str = "",
    source_date: str = "",
) -> list[dict]:
    """Build preview blocks for multi-ticket creation.

    Shows extracted items in a table with edit/remove actions per row.
    Epics displayed first, then stories with hierarchy indication.

    Args:
        items: List of extracted items with id, type, title, description, parent_id
        ui_version: Version for stale button detection
        source_persona: Persona that created the review (e.g., "Technical Architect")
        source_date: Date of the review

    Returns:
        Slack blocks for preview UI
    """
    # Build epic lookup for parent reference
    epic_titles: dict[str, str] = {}
    for item in items:
        if item["type"] == "epic":
            epic_titles[item["id"]] = item["title"]

    # Sort items: epics first, then stories
    sorted_items = sorted(items, key=lambda x: (0 if x["type"] == "epic" else 1, x.get("title", "")))

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Create {len(items)} Jira Tickets",
            },
        },
    ]

    # Add source context if available
    if source_persona or source_date:
        context_parts = []
        if source_persona and source_date:
            context_parts.append(f"From {source_persona} Review on {source_date}")
        elif source_persona:
            context_parts.append(f"From {source_persona} Review")
        elif source_date:
            context_parts.append(f"From Review on {source_date}")

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": context_parts[0]},
            ],
        })

    blocks.append({"type": "divider"})

    # Build item rows
    for item in sorted_items:
        item_id = item["id"]
        item_type = item["type"]
        title = item.get("title", "Untitled")
        description = item.get("description", "")
        parent_id = item.get("parent_id")

        # Type emoji: Epic = target, Story = memo
        emoji = "\U0001f3af" if item_type == "epic" else "\U0001f4dd"  # 🎯 or 📝

        # Truncate description
        truncated_desc = description[:100] + "..." if len(description) > 100 else description

        # Build item text
        item_text = f"{emoji} *{title}*\n_{truncated_desc}_"

        # Add parent reference for stories
        if parent_id and parent_id in epic_titles:
            item_text += f"\n\u21b3 Under: {epic_titles[parent_id]}"  # ↳

        # Section with Edit and Remove buttons
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": item_text,
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": f"multi_ticket_edit_item:{item_id}:{ui_version}",
            },
        })

        # Remove button as separate action row for this item
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Remove"},
                    "action_id": f"multi_ticket_remove_item:{item_id}:{ui_version}",
                    "style": "danger",
                },
            ],
        })

    blocks.append({"type": "divider"})

    # Action buttons row
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
                "text": {"type": "plain_text", "text": "Add Item"},
                "action_id": f"multi_ticket_add_item:{ui_version}",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Cancel"},
                "action_id": "multi_ticket_cancel",
                "style": "danger",
            },
        ],
    })

    return blocks


def build_creation_progress_blocks(
    items: list[dict[str, Any]],
    results: list[dict[str, Any]],
    current_idx: Optional[int] = None,
) -> list[dict]:
    """Build blocks showing creation progress.

    Shows live status for each item during batch creation:
    - Checkmark for success
    - X for failed
    - Spinner for current
    - Square for pending

    Args:
        items: All items being created (in creation order)
        results: Creation results so far
        current_idx: Index of item currently being created (None if done)

    Returns:
        Slack blocks showing progress
    """
    # Build lookup for results
    result_lookup: dict[str, dict] = {r["item_id"]: r for r in results}

    # Count successes and failures
    success_count = sum(1 for r in results if r.get("success"))
    failure_count = sum(1 for r in results if not r.get("success"))

    # Header
    if current_idx is not None:
        header_text = "Creating Jira Tickets..."
    elif failure_count > 0:
        header_text = f"Created {success_count} of {len(items)} tickets ({failure_count} failed)"
    else:
        header_text = f"Created {success_count} Jira Tickets"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text,
            },
        },
        {"type": "divider"},
    ]

    # Build item rows
    for idx, item in enumerate(items):
        item_id = item.get("id", "")
        item_type = item.get("type", "story")
        title = item.get("title", "Untitled")

        # Type label
        type_label = "Epic" if item_type == "epic" else "Story"

        # Determine status
        result = result_lookup.get(item_id)
        if result:
            if result.get("success"):
                # Success - show checkmark and Jira key link
                jira_key = result.get("jira_key", "")
                jira_url = result.get("jira_url", "")
                if jira_url:
                    status_text = f":white_check_mark: *{type_label}* {title} -> <{jira_url}|{jira_key}>"
                else:
                    status_text = f":white_check_mark: *{type_label}* {title} -> {jira_key}"
            else:
                # Failed - show X and error
                error = result.get("error", "Unknown error")
                # Truncate long errors
                if len(error) > 100:
                    error = error[:100] + "..."
                status_text = f":x: *{type_label}* {title} - Failed: {error}"
        elif current_idx is not None and idx == current_idx:
            # Currently being created - show spinner
            status_text = f":hourglass_flowing_sand: *{type_label}* {title}"
        else:
            # Pending - show square
            status_text = f":white_square: *{type_label}* {title}"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": status_text,
            },
        })

    blocks.append({"type": "divider"})

    # Progress count
    if current_idx is not None:
        progress_text = f"{len(results)} of {len(items)} created"
    else:
        progress_text = f"Done: {success_count} created, {failure_count} failed"

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": progress_text},
        ],
    })

    # Add retry button when done with failures
    if current_idx is None and failure_count > 0:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"Retry Failed ({failure_count})"},
                    "action_id": "multi_ticket_retry_failed",
                    "style": "primary",
                },
            ],
        })

    return blocks
