"""Decision view, history, and display toggle handlers.

Handles viewing decision details, version history, and
expanding/collapsing decision cards in place.

INVARIANT I2: Slack = UI
Handlers are READ-ONLY - no state mutations.
"""
import json
import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


# =============================================================================
# View Decision History
# =============================================================================


def handle_decision_history(ack, body, client: WebClient):
    """Handle decision history button click.

    Shows version history for a decision.
    """
    ack()
    _run_async(_handle_decision_history_async(body, client))


async def _handle_decision_history_async(body, client: WebClient):
    """Async handler for decision history."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore

    # Extract data
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_history button value: {button_value}")
        return

    decision_id = data.get("decision_id")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    thread_ts = message.get("thread_ts") or message.get("ts")

    async with get_connection() as conn:
        store = DecisionStore(conn)
        decision = await store.get(decision_id)
        history = await store.get_version_history(decision_id)

    if not decision:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Decision not found.",
        )
        return

    # Build history blocks
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"History: DEC-{decision_id[:8]}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Current (v{decision.version}):* {decision.title}",
            },
        },
    ]

    if not history:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No previous versions_"},
        })
    else:
        blocks.append({"type": "divider"})
        for version in history[:10]:  # Limit to 10 versions
            version_text = f"*v{version.version}* ({version.changed_at.strftime('%Y-%m-%d %H:%M')})\n"
            version_text += f"_{version.title}_\n"
            if version.change_reason:
                version_text += f"Reason: {version.change_reason}\n"
            version_text += f"Changed by: <@{version.changed_by}>"

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": version_text},
            })

    # Post as thread reply
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=blocks,
        text=f"History for DEC-{decision_id[:8]}",
    )


# =============================================================================
# View Decision (from list)
# =============================================================================


def handle_decision_view(ack, body, client: WebClient):
    """Handle decision view button click.

    Shows decision details (used from /maro decisions list).
    """
    ack()
    _run_async(_handle_decision_view_async(body, client))


async def _handle_decision_view_async(body, client: WebClient):
    """Async handler for decision view."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.schemas.decision import DecisionStatus, DecisionType
    from src.slack.handlers.decision_commands import _get_type_emoji

    # Extract data
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_view button value: {button_value}")
        return

    decision_id = data.get("decision_id")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]

    async with get_connection() as conn:
        store = DecisionStore(conn)
        link_store = DecisionLinkStore(conn)
        decision = await store.get(decision_id)
        links = await link_store.get_links_for_decision(decision_id)

    if not decision:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Decision not found.",
        )
        return

    linked_tickets = [link.jira_key for link in links]

    # Build detail blocks (same as decision_commands.py)
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
# Cancel Action (generic)
# =============================================================================


def handle_decision_cancel(ack, body, client: WebClient):
    """Handle decision cancel button click.

    Generic cancel that dismisses UI without action.
    """
    ack()
    # No-op - just dismiss
    logger.info("Decision action cancelled")


# =============================================================================
# Show/Hide Details (in-place card toggle)
# =============================================================================


def handle_decision_show_details(ack, body, client: WebClient):
    """Handle show details button - expands card in place."""
    ack()
    _run_async(_handle_decision_show_details_async(body, client))


async def _handle_decision_show_details_async(body, client: WebClient):
    """Async handler for show details - updates card to expanded view."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.slack.blocks.decision_cards import build_expanded_approved_card

    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_show_details button value: {button_value}")
        return

    decision_id = data.get("decision_id")
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    message_ts = message.get("ts")

    async with get_connection() as conn:
        store = DecisionStore(conn)
        link_store = DecisionLinkStore(conn)
        decision = await store.get(decision_id)
        links = await link_store.get_links_for_decision(decision_id)

    if not decision:
        logger.warning(f"Decision not found for show_details: {decision_id}")
        return

    linked_tickets = [link.jira_key for link in links]

    # Update card in place to expanded view
    try:
        expanded_blocks = build_expanded_approved_card(decision, linked_tickets)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=expanded_blocks,
            text=f"Decision DEC-{decision_id[:8]} (expanded)",
        )
    except Exception as e:
        logger.error(f"Failed to expand decision card: {e}")


def handle_decision_hide_details(ack, body, client: WebClient):
    """Handle hide details button - collapses card back to compact view."""
    ack()
    _run_async(_handle_decision_hide_details_async(body, client))


async def _handle_decision_hide_details_async(body, client: WebClient):
    """Async handler for hide details - updates card to compact view."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.slack.blocks.decision_cards import build_approved_card

    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_hide_details button value: {button_value}")
        return

    decision_id = data.get("decision_id")
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    message_ts = message.get("ts")

    async with get_connection() as conn:
        store = DecisionStore(conn)
        link_store = DecisionLinkStore(conn)
        decision = await store.get(decision_id)
        links = await link_store.get_links_for_decision(decision_id)

    if not decision:
        logger.warning(f"Decision not found for hide_details: {decision_id}")
        return

    linked_tickets = [link.jira_key for link in links]

    # Update card in place to compact view
    try:
        compact_blocks = build_approved_card(decision, linked_tickets)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=compact_blocks,
            text=f"Decision DEC-{decision_id[:8]}",
        )
    except Exception as e:
        logger.error(f"Failed to collapse decision card: {e}")
