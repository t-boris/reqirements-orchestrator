"""Slack blocks for duplicate ticket handling."""


def build_duplicate_blocks(
    potential_duplicates: list[dict],
    session_id: str,
    draft_hash: str,
) -> list[dict]:
    """Build blocks for duplicate detection with action buttons.

    Shows rich duplicate display with match explanation and action buttons:
    - Link to this: Bind thread to existing ticket
    - Add as info: Add conversation info to existing ticket (stub)
    - Create new: Proceed with new ticket creation
    - Show more: Open modal with all matches

    Args:
        potential_duplicates: List of dicts with key, summary, url, status, assignee, updated, match_reason
        session_id: Session ID for button value encoding
        draft_hash: Hash of draft content for version checking

    Returns:
        List of Slack block dicts for duplicate display
    """
    if not potential_duplicates:
        return []

    blocks = []

    # Header
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": ":mag: *Possible existing ticket found*"
        }
    })

    # Best match (first duplicate)
    best = potential_duplicates[0]
    key = best.get("key", "Unknown")
    summary = best.get("summary", "")[:60]
    if len(best.get("summary", "")) > 60:
        summary += "..."
    url = best.get("url", "#")
    status = best.get("status", "Unknown")
    assignee = best.get("assignee", "Unassigned") or "Unassigned"
    updated = best.get("updated", "Unknown")
    match_reason = best.get("match_reason", "")

    # Main ticket info
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"I found a Jira ticket that looks very similar:\n\n"
                    f"*<{url}|{key}>* - \"{summary}\"\n"
                    f"Status: {status} | Assignee: {assignee} | Updated: {updated}"
        }
    })

    # Match reason (if available)
    if match_reason:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f":bulb: *This matches because:* {match_reason}"
            }]
        })

    # Action buttons
    # Button value encoding: action:session_id:draft_hash:issue_key
    has_more = len(potential_duplicates) > 1

    action_buttons = [
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Link to this",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}:{key}",
            "action_id": "link_duplicate",
            "style": "primary",
        },
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Add as info",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}:{key}",
            "action_id": "add_to_duplicate",
        },
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Create new",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}",
            "action_id": "create_anyway",
        },
    ]

    # Add "Show more" button if there are additional matches
    if has_more:
        action_buttons.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": f"Show more ({len(potential_duplicates) - 1})",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}",
            "action_id": "show_more_duplicates",
        })

    blocks.append({
        "type": "actions",
        "elements": action_buttons
    })

    return blocks
