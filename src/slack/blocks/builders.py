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
    approved_items: list[dict[str, str]] | None = None,
    committed_items: list[dict[str, str]] | None = None,
    decision_items: list[dict[str, str]] | None = None,
    channel_id: str | None = None,
    jira_url: str | None = None,
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

    # Pending approvals section (Draft/Proposed work items)
    if pending_count > 0:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Pending Approval ({pending_count})*"},
        })
        if pending_items:
            for item in pending_items[:5]:
                title = item.get('title', 'Untitled')
                link = item.get('link')
                parent_title = item.get('parent_title')
                # Show hierarchy with arrow prefix for child items
                if parent_title:
                    prefix = f"↳ _{parent_title}_ → "
                else:
                    prefix = "* "
                text = f"{prefix}<{link}|{title}>" if link else f"{prefix}{title}"
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": text}],
                })

    # Approved (ready for Jira) section
    if approved_count > 0:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Ready for Jira ({approved_count})*"},
        })
        if approved_items:
            for item in approved_items[:5]:
                title = item.get('title', 'Untitled')
                link = item.get('link')
                parent_title = item.get('parent_title')
                # Show hierarchy with arrow prefix for child items
                if parent_title:
                    prefix = f"↳ _{parent_title}_ → :white_check_mark: "
                else:
                    prefix = "* :white_check_mark: "
                text = f"{prefix}<{link}|{title}>" if link else f"{prefix}{title}"
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": text}],
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
                link = item.get("link")
                parent_title = item.get("parent_title")
                parent_jira_key = item.get("parent_jira_key")
                # Build prefix showing hierarchy
                if parent_title:
                    if parent_jira_key:
                        prefix = f"↳ _{parent_jira_key}_ → "
                    else:
                        prefix = f"↳ _{parent_title}_ → "
                else:
                    prefix = "* "
                # Link title to Slack message if available
                title_display = f"<{link}|{title}>" if link else title
                # Link to Jira if we have URL
                if jira_url and jira_key != "draft":
                    jira_link = f"<{jira_url}/browse/{jira_key}|{jira_key}>"
                    text = f"{prefix}[{jira_link}] {title_display}"
                else:
                    text = f"{prefix}[{jira_key}] {title_display}"
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": text}],
                })

    # Active decisions section
    if decisions_count > 0:
        active_count = sum(1 for d in (decision_items or []) if d.get("status") != "deprecated")
        deprecated_count = sum(1 for d in (decision_items or []) if d.get("status") == "deprecated")
        header = f"*Active Decisions ({active_count})*"
        if deprecated_count:
            header += f" · {deprecated_count} deprecated"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": header},
        })
        if decision_items:
            # Show active decisions first (max 5), then deprecated (max 2)
            active_items = [d for d in decision_items if d.get("status") != "deprecated"]
            deprecated_items = [d for d in decision_items if d.get("status") == "deprecated"]
            display_items = active_items[:5] + deprecated_items[:2]
            for item in display_items:
                title = item.get("title", "Untitled")
                link = item.get("link")
                status = item.get("status", "draft")

                if status == "deprecated":
                    display = f"~{title}~ _(deprecated)_"
                elif status == "committed":
                    display = f":white_check_mark: {title}"
                elif status == "proposed":
                    display = f":hourglass: {title}"
                else:  # draft
                    display = f":pencil2: {title}"

                text = f"* <{link}|{display}>" if link else f"* {display}"
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": text}],
                })

            # Overflow indicators
            if len(active_items) > 5:
                overflow = len(active_items) - 5
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"_...and {overflow} more active decisions_"}],
                })
            if len(deprecated_items) > 2:
                overflow = len(deprecated_items) - 2
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"_...and {overflow} more deprecated_"}],
                })

    # "Show all" button when items overflow
    has_overflow = False
    if decision_items:
        active_items = [d for d in decision_items if d.get("status") != "deprecated"]
        deprecated_items = [d for d in decision_items if d.get("status") == "deprecated"]
        if len(active_items) > 5 or len(deprecated_items) > 2:
            has_overflow = True
    if pending_items and len(pending_items) > 5:
        has_overflow = True
    if committed_items and len(committed_items) > 5:
        has_overflow = True

    if has_overflow and channel_id:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Show all items"},
                "action_id": "dashboard_show_all",
                "value": channel_id,
            }],
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
