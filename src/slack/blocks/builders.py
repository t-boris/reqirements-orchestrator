"""Block Kit message builders.

Ref: Spec Part 8 - ApprovalHandler._build_proposal_blocks
Ref: RESEARCH.md - Button Blocks Builder
"""
from datetime import datetime
from typing import Any

from src.domain.types import EntityId


def build_approval_blocks(
    entity_id: EntityId,
    title: str,
    description: str | None = None,
    issue_type: str | None = None,
) -> list[dict[str, Any]]:
    """Build approval blocks with Approve/Object/Discuss buttons.

    Used when proposing work items for channel approval.
    """
    blocks: list[dict[str, Any]] = []

    # Header with issue type badge if provided
    header_text = f"*{title}*"
    if issue_type:
        header_text = f":{_issue_type_emoji(issue_type)}: {header_text}"

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": header_text},
    })

    # Description if provided
    if description:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": description[:2000]},  # Block limit
        })

    blocks.append({"type": "divider"})

    # Action buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "style": "primary",
                "action_id": f"approve_{entity_id}",
                "value": str(entity_id),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Object"},
                "action_id": f"object_{entity_id}",
                "value": str(entity_id),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Discuss"},
                "action_id": f"discuss_{entity_id}",
                "value": str(entity_id),
            },
        ],
    })

    return blocks


def build_decision_blocks(
    entity_id: EntityId,
    title: str,
    decision_type: str,
    description: str | None = None,
) -> list[dict[str, Any]]:
    """Build decision proposal blocks.

    Used when proposing decisions for channel approval.
    """
    blocks: list[dict[str, Any]] = []

    # Header with decision type
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f":memo: *Decision: {title}*"},
    })

    # Decision type context
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Type: {decision_type}"}],
    })

    if description:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": description[:2000]},
        })

    blocks.append({"type": "divider"})

    # Approve/Object only for decisions (no Discuss)
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "style": "primary",
                "action_id": f"approve_{entity_id}",
                "value": str(entity_id),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Object"},
                "action_id": f"object_{entity_id}",
                "value": str(entity_id),
            },
        ],
    })

    return blocks


def build_dashboard_blocks(
    pending_count: int = 0,
    approved_count: int = 0,
    committed_count: int = 0,
    decisions_count: int = 0,
    pending_items: list[dict[str, str]] | None = None,
    committed_items: list[dict[str, str]] | None = None,
    decision_items: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Build channel status dashboard blocks.

    Ref: Spec Part 9.3 - DashboardManager._build_dashboard_blocks
    """
    blocks: list[dict[str, Any]] = []

    # Header
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": ":bar_chart: Channel Status"},
    })
    blocks.append({"type": "divider"})

    # Pending approvals section
    if pending_count > 0:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Pending Approval ({pending_count})*"},
        })
        if pending_items:
            for item in pending_items[:5]:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"* {item.get('title', 'Untitled')}"}],
                })

    # Committed (in Jira) section
    if committed_count > 0:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*In Jira ({committed_count})*"},
        })
        if committed_items:
            for item in committed_items[:5]:
                jira_key = item.get("jira_key", "draft")
                title = item.get("title", "Untitled")
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"* [{jira_key}] {title}"}],
                })

    # Active decisions section
    if decisions_count > 0:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Active Decisions ({decisions_count})*"},
        })
        if decision_items:
            for item in decision_items[:5]:
                title = item.get("title", "Untitled")
                link = item.get("link")
                text = f"* <{link}|{title}>" if link else f"* {title}"
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": text}],
                })

    blocks.append({"type": "divider"})

    # Footer with timestamp
    now = int(datetime.utcnow().timestamp())
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"_Last updated: <!date^{now}^{{date_short}} {{time}}|now>_",
        }],
    })

    return blocks


def build_error_blocks(
    error_message: str,
    suggestion: str | None = None,
) -> list[dict[str, Any]]:
    """Build error message blocks."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":warning: {error_message}"},
        },
    ]

    if suggestion:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": suggestion}],
        })

    return blocks


def build_help_blocks(commands: dict[str, str]) -> list[dict[str, Any]]:
    """Build help message blocks."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "MARO Commands"},
        },
        {"type": "divider"},
    ]

    for cmd, desc in commands.items():
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"`/maro {cmd}` - {desc}"},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "_MARO 2.0 - Threads propose. Channels decide. Jira executes._",
        }],
    })

    return blocks


def _issue_type_emoji(issue_type: str) -> str:
    """Get emoji for issue type."""
    return {
        "epic": "large_purple_circle",
        "story": "large_blue_circle",
        "task": "white_circle",
        "bug": "red_circle",
        "spike": "mag",
    }.get(issue_type.lower(), "white_circle")
