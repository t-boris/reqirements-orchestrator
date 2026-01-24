"""Decision management commands for /maro decisions.

Commands:
- /maro decisions - List channel decisions with filters
- /maro decision show <id> - Show decision details with linked tickets
- /maro decision change <id> - Propose change (creates new version)
- /maro decision deprecate <id> - Mark as deprecated
"""
import json
import logging

from slack_sdk.web import WebClient

from src.db.connection import get_connection
from src.db.decision_link_store import DecisionLinkStore
from src.db.decision_store import DecisionStore
from src.schemas.decision import Decision, DecisionStatus, DecisionType
from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def handle_decisions_command(ack, body, client: WebClient):
    """Handle /maro decisions command.

    Usage:
    - /maro decisions - List all active decisions
    - /maro decisions arch - Filter by type
    - /maro decisions all - Include deprecated
    """
    ack()
    _run_async(_handle_decisions_command_async(body, client))


async def _handle_decisions_command_async(body, client: WebClient):
    """List decisions for channel."""
    channel_id = body["channel_id"]
    user_id = body["user_id"]
    text = body.get("text", "").strip()

    # Parse filters
    include_deprecated = "all" in text.lower()
    type_filter = None

    for dtype in DecisionType:
        if dtype.value in text.lower():
            type_filter = dtype
            break

    # Fetch decisions
    async with get_connection() as conn:
        store = DecisionStore(conn)

        statuses = None
        if not include_deprecated:
            statuses = [DecisionStatus.PROPOSED, DecisionStatus.APPROVED]

        decisions = await store.list_by_channel(
            channel_id=channel_id,
            status=statuses,
            decision_type=type_filter,
            limit=20,
        )

    if not decisions:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="No decisions found in this channel.",
        )
        return

    # Build blocks
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Channel Decisions"},
        },
    ]

    # Group by status
    by_status: dict[DecisionStatus, list[Decision]] = {}
    for d in decisions:
        by_status.setdefault(d.status, []).append(d)

    # Active first
    for status in [DecisionStatus.APPROVED, DecisionStatus.PROPOSED, DecisionStatus.DEPRECATED]:
        if status not in by_status:
            continue

        status_label = {
            DecisionStatus.APPROVED: "Active",
            DecisionStatus.PROPOSED: "Proposed",
            DecisionStatus.DEPRECATED: "Deprecated",
        }.get(status, status.value)

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{status_label}*"},
        })

        for d in by_status[status]:
            type_emoji = _get_type_emoji(d.decision_type)
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{type_emoji} *DEC-{d.id[:8]}* ({d.decision_type.value.upper()})\n{d.title}",
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View"},
                    "action_id": "decision_view",
                    "value": json.dumps({"decision_id": d.id}),
                },
            })

        blocks.append({"type": "divider"})

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        blocks=blocks,
        text="Channel decisions",
    )


def _get_type_emoji(decision_type: DecisionType) -> str:
    """Get emoji for decision type."""
    return {
        DecisionType.ARCH: ":brain:",
        DecisionType.SCOPE: ":triangular_ruler:",
        DecisionType.CONSTRAINT: ":lock:",
        DecisionType.PRIORITY: ":zap:",
        DecisionType.STRUCTURE: ":building_construction:",
        DecisionType.PROCESS: ":gear:",
    }.get(decision_type, ":brain:")


# =============================================================================
# /maro decision show <id>
# =============================================================================


def handle_decision_show_command(ack, body, client: WebClient):
    """Handle /maro decision show <id> command.

    Shows decision details with linked Jira tickets.
    """
    ack()
    _run_async(_handle_decision_show_async(body, client))


async def _handle_decision_show_async(body, client: WebClient):
    """Show decision details."""
    channel_id = body["channel_id"]
    user_id = body["user_id"]
    text = body.get("text", "").strip()

    # Extract decision ID from text
    # Expected: "show DEC-abc123" or "show abc123"
    parts = text.split()
    if len(parts) < 2:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Usage: /maro decision show <decision-id>",
        )
        return

    decision_id_input = parts[1].upper().replace("DEC-", "")

    async with get_connection() as conn:
        store = DecisionStore(conn)
        link_store = DecisionLinkStore(conn)

        # Find decision by prefix
        decisions = await store.list_by_channel(channel_id, limit=100)
        decision = None
        for d in decisions:
            if d.id.startswith(decision_id_input) or d.id[:8].upper() == decision_id_input:
                decision = d
                break

        if not decision:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Decision `{decision_id_input}` not found in this channel.",
            )
            return

        # Get linked tickets
        links = await link_store.get_links_for_decision(decision.id)

    linked_tickets = [link.jira_key for link in links]

    # Build detail blocks
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.upper()
    status_label = decision.status.value.upper()

    blocks = [
        {"type": "divider"},
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Decision DEC-{decision.id[:8]}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Type:*\n{type_emoji} {type_label}"},
                {"type": "mrkdwn", "text": f"*Status:*\n{status_label}"},
                {"type": "mrkdwn", "text": f"*Version:*\nv{decision.version}"},
                {
                    "type": "mrkdwn",
                    "text": f"*Created by:*\n<@{decision.created_by}>",
                },
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Title:*\n{decision.title}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Description:*\n{decision.description}"},
        },
    ]

    # Add linked tickets
    if linked_tickets:
        tickets_text = ", ".join(linked_tickets)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Linked Jira tickets:*\n{tickets_text}"},
        })

    # Add approval info
    if decision.approved_by and decision.approved_at:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Approved by <@{decision.approved_by}> on {decision.approved_at.strftime('%Y-%m-%d %H:%M')}",
                },
            ],
        })

    # Add action buttons based on status
    if decision.status == DecisionStatus.PROPOSED:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "decision_approve",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "action_id": "decision_edit",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
            ],
        })
    elif decision.status == DecisionStatus.APPROVED:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Change"},
                    "action_id": "decision_change",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deprecate"},
                    "style": "danger",
                    "action_id": "decision_deprecate",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "History"},
                    "action_id": "decision_history",
                    "value": json.dumps({"decision_id": decision.id}),
                },
            ],
        })

    blocks.append({"type": "divider"})

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        blocks=blocks,
        text=f"Decision DEC-{decision.id[:8]}",
    )


# =============================================================================
# /maro decision change <id>
# =============================================================================


def handle_decision_change_command(ack, body, client: WebClient):
    """Handle /maro decision change <id> command.

    Opens modal to propose changes to a decision (creates new version).
    """
    ack()
    _run_async(_handle_decision_change_async(body, client))


async def _handle_decision_change_async(body, client: WebClient):
    """Open change proposal modal."""
    channel_id = body["channel_id"]
    user_id = body["user_id"]
    trigger_id = body["trigger_id"]
    text = body.get("text", "").strip()

    # Extract decision ID
    parts = text.split()
    if len(parts) < 2:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Usage: /maro decision change <decision-id>",
        )
        return

    decision_id_input = parts[1].upper().replace("DEC-", "")

    async with get_connection() as conn:
        store = DecisionStore(conn)

        # Find decision by prefix
        decisions = await store.list_by_channel(channel_id, limit=100)
        decision = None
        for d in decisions:
            if d.id.startswith(decision_id_input) or d.id[:8].upper() == decision_id_input:
                decision = d
                break

    if not decision:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Decision `{decision_id_input}` not found in this channel.",
        )
        return

    if decision.status == DecisionStatus.DEPRECATED:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Cannot change deprecated decision DEC-{decision.id[:8]}.",
        )
        return

    # Open modal with current values
    modal = {
        "type": "modal",
        "callback_id": "decision_change_modal",
        "private_metadata": json.dumps({
            "decision_id": decision.id,
            "channel_id": channel_id,
        }),
        "title": {"type": "plain_text", "text": f"Change DEC-{decision.id[:8]}"},
        "submit": {"type": "plain_text", "text": "Propose Change"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Current version: *v{decision.version}*\nThis will create a new proposed version.",
                },
            },
            {
                "type": "input",
                "block_id": "title_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "title_input",
                    "initial_value": decision.title,
                    "placeholder": {"type": "plain_text", "text": "Decision title"},
                },
                "label": {"type": "plain_text", "text": "Title"},
            },
            {
                "type": "input",
                "block_id": "description_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "description_input",
                    "multiline": True,
                    "initial_value": decision.description,
                    "placeholder": {"type": "plain_text", "text": "Full description"},
                },
                "label": {"type": "plain_text", "text": "Description"},
            },
            {
                "type": "input",
                "block_id": "reason_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "reason_input",
                    "placeholder": {"type": "plain_text", "text": "Why this change?"},
                },
                "label": {"type": "plain_text", "text": "Reason for change"},
            },
        ],
    }

    client.views_open(trigger_id=trigger_id, view=modal)


# =============================================================================
# /maro decision deprecate <id>
# =============================================================================


def handle_decision_deprecate_command(ack, body, client: WebClient):
    """Handle /maro decision deprecate <id> command.

    Opens modal to deprecate a decision with reason.
    """
    ack()
    _run_async(_handle_decision_deprecate_async(body, client))


async def _handle_decision_deprecate_async(body, client: WebClient):
    """Open deprecation modal."""
    channel_id = body["channel_id"]
    user_id = body["user_id"]
    trigger_id = body["trigger_id"]
    text = body.get("text", "").strip()

    # Extract decision ID
    parts = text.split()
    if len(parts) < 2:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Usage: /maro decision deprecate <decision-id>",
        )
        return

    decision_id_input = parts[1].upper().replace("DEC-", "")

    async with get_connection() as conn:
        store = DecisionStore(conn)

        # Find decision by prefix
        decisions = await store.list_by_channel(channel_id, limit=100)
        decision = None
        for d in decisions:
            if d.id.startswith(decision_id_input) or d.id[:8].upper() == decision_id_input:
                decision = d
                break

    if not decision:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Decision `{decision_id_input}` not found in this channel.",
        )
        return

    if decision.status == DecisionStatus.DEPRECATED:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Decision DEC-{decision.id[:8]} is already deprecated.",
        )
        return

    # Open deprecation modal
    modal = {
        "type": "modal",
        "callback_id": "decision_deprecate_modal",
        "private_metadata": json.dumps({
            "decision_id": decision.id,
            "channel_id": channel_id,
        }),
        "title": {"type": "plain_text", "text": f"Deprecate DEC-{decision.id[:8]}"},
        "submit": {"type": "plain_text", "text": "Deprecate"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{decision.title}*\n\nThis will mark the decision as deprecated. It will no longer affect Jira tickets.",
                },
            },
            {
                "type": "input",
                "block_id": "reason_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "reason_input",
                    "placeholder": {"type": "plain_text", "text": "Why is this being deprecated?"},
                },
                "label": {"type": "plain_text", "text": "Deprecation reason"},
            },
            {
                "type": "input",
                "block_id": "replacement_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "replacement_input",
                    "placeholder": {"type": "plain_text", "text": "DEC-xxxxxxxx (optional)"},
                },
                "label": {"type": "plain_text", "text": "Replaced by (decision ID)"},
            },
        ],
    }

    client.views_open(trigger_id=trigger_id, view=modal)
