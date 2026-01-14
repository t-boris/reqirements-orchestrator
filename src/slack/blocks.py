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


def build_draft_preview_blocks(draft: "TicketDraft") -> list[dict]:
    """Build Slack blocks for ticket draft preview (legacy).

    Shows all draft fields with approval buttons.
    Note: Use build_draft_preview_blocks_with_hash for version-checked previews.
    """
    # Use new function with None hash (legacy behavior)
    return build_draft_preview_blocks_with_hash(
        draft=draft,
        session_id=draft.id,
        draft_hash="",
        evidence_permalinks=None,
    )


def build_draft_preview_blocks_with_hash(
    draft: "TicketDraft",
    session_id: str,
    draft_hash: str,
    evidence_permalinks: Optional[list[dict]] = None,
) -> list[dict]:
    """Build Slack blocks for ticket draft preview with version hash.

    Embeds draft_hash in button values for version checking.
    Shows evidence links inline with permalinks.

    Args:
        draft: TicketDraft to display
        session_id: Session ID for button value prefix
        draft_hash: Hash of draft content for version checking
        evidence_permalinks: Optional list of {permalink, user, preview} dicts
    """
    from src.schemas.draft import TicketDraft

    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Ticket Preview",
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

    # Constraints (if present)
    if draft.constraints:
        constraints_text = "*Constraints:*\n"
        for c in draft.constraints:
            constraints_text += f"• `{c.key}` = `{c.value}` ({c.status.value})\n"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": constraints_text
            }
        })

    # Evidence sources (if provided)
    if evidence_permalinks:
        sources_text = "*Sources:*\n"
        for evidence in evidence_permalinks[:3]:  # Max 3 sources
            permalink = evidence.get("permalink", "#")
            user = evidence.get("user", "user")
            preview = evidence.get("preview", "")[:50]
            if len(evidence.get("preview", "")) > 50:
                preview += "..."
            sources_text += f"• <{permalink}|Message from @{user}>: \"{preview}\"\n"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": sources_text
            }
        })

    # Divider
    blocks.append({"type": "divider"})

    # Build button value with session_id:draft_hash for version checking
    button_value = f"{session_id}:{draft_hash}" if draft_hash else session_id

    # Approval buttons with embedded hash
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Approve & Create",
                    "emoji": True
                },
                "value": button_value,
                "action_id": "approve_draft",
                "style": "primary",
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Needs Changes",
                    "emoji": True
                },
                "value": button_value,
                "action_id": "reject_draft",
            },
        ]
    })

    # Context with evidence count
    evidence_count = len(draft.evidence_links) if draft.evidence_links else 0
    context_text = f"Draft version {draft.version}"
    if evidence_count > 0:
        context_text += f" | Based on {evidence_count} messages"

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": context_text
        }]
    })

    return blocks
