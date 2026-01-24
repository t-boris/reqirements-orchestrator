"""Decision button handlers for lifecycle management.

Handles button clicks on decision cards:
- decision_approve: Approve a proposed decision -> triggers Jira sync
- decision_edit: Open edit modal for proposed decision
- decision_discard: Delete/discard a proposed decision
- decision_change: Open change modal for approved decision (creates new version)
- decision_deprecate: Open deprecation modal
- decision_history: Show version history
- decision_view: Show decision details
- decision_cancel: Cancel approval/change action

All handlers follow pattern: sync ack() + async via _run_async().
"""
import json
import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


# =============================================================================
# Approve Decision
# =============================================================================


def handle_decision_approve(ack, body, client: WebClient):
    """Handle decision approval button click.

    Approves decision and triggers sync to linked Jira tickets.
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_decision_approve_async(body, client))


async def _handle_decision_approve_async(body, client: WebClient):
    """Async handler for decision approval.

    CRITICAL ORDER:
    1. Database state update (truth)
    2. Jira sync (projection)
    3. Slack message (presentation - best effort)
    Slack failure must NOT affect 1 or 2
    """
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.sync.decision_sync import DecisionSyncService
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.slack.blocks.decision_cards import build_approved_card

    # Extract data from button
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_approve button value: {button_value}")
        return

    decision_id = data.get("decision_id")
    expected_version = data.get("version")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    message_ts = message.get("ts")

    logger.info(
        "Decision approve button clicked",
        extra={
            "decision_id": decision_id,
            "version": expected_version,
            "user_id": user_id,
        }
    )

    settings = get_settings()
    jira_service = JiraService(settings)
    linked_tickets: list[str] = []
    sync_result = None

    try:
        async with get_connection() as conn:
            store = DecisionStore(conn)
            link_store = DecisionLinkStore(conn)

            # Get current decision
            decision = await store.get(decision_id)
            if not decision:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text="Decision not found.",
                )
                return

            # Version check for stale UI
            if expected_version and decision.version != expected_version:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"This decision has been modified (v{expected_version} -> v{decision.version}). Please refresh and try again.",
                )
                return

            # =================================================================
            # STEP 1: Database state update (TRUTH) - MUST succeed first
            # =================================================================
            approved_decision = await store.approve(decision_id, user_id)

            # Get linked tickets for UI and sync
            links = await link_store.get_links_for_decision(decision_id)
            linked_tickets = [link.jira_key for link in links]

            # =================================================================
            # STEP 2: Jira sync (PROJECTION) - proceeds regardless of Slack
            # =================================================================
            if links:
                sync_service = DecisionSyncService(
                    jira_service=jira_service,
                    decision_store=store,
                    link_store=link_store,
                )
                sync_result = await sync_service.sync_decision(decision_id)

        # =====================================================================
        # STEP 3: Slack message (PRESENTATION) - best effort, doesn't block
        # =====================================================================
        try:
            approved_blocks = build_approved_card(approved_decision, linked_tickets)
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=approved_blocks,
                text=f"Decision DEC-{decision_id[:8]} approved",
            )
        except Exception as slack_err:
            # Slack message update failed, but decision is approved and synced
            logger.warning(
                "Slack message update failed, but decision is approved and synced",
                extra={
                    "decision_id": decision_id,
                    "version": approved_decision.version,
                    "error": str(slack_err),
                }
            )

        # Report sync result in thread (also best effort)
        if sync_result:
            try:
                if sync_result.all_synced:
                    client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=message_ts,
                        text=f"Decision synced to {sync_result.synced_count} Jira ticket(s).",
                    )
                elif sync_result.has_conflicts:
                    conflict_tickets = [
                        r.jira_key for r in sync_result.ticket_results
                        if r.preflight_result and not r.success
                    ]
                    client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=message_ts,
                        text=f"Synced to {sync_result.synced_count} ticket(s). {sync_result.blocked_count} blocked by conflicts: {', '.join(conflict_tickets)}",
                    )
                elif sync_result.failed_count > 0:
                    client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=message_ts,
                        text=f"Synced to {sync_result.synced_count} ticket(s). {sync_result.failed_count} failed.",
                    )
            except Exception as slack_thread_err:
                logger.warning(
                    "Failed to post sync result to thread",
                    extra={
                        "decision_id": decision_id,
                        "error": str(slack_thread_err),
                    }
                )

        logger.info(
            "Decision approved",
            extra={
                "decision_id": decision_id,
                "approved_by": user_id,
                "linked_tickets": linked_tickets,
            }
        )

    except ValueError as e:
        # Decision not in proposed status or other validation error
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to approve decision: {e}", exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Failed to approve decision: {str(e)}",
        )
    finally:
        await jira_service.close()


# =============================================================================
# Edit Decision
# =============================================================================


def handle_decision_edit(ack, body, client: WebClient):
    """Handle decision edit button click.

    Opens modal to edit title/description of a proposed decision.
    """
    ack()
    _run_async(_handle_decision_edit_async(body, client))


async def _handle_decision_edit_async(body, client: WebClient):
    """Async handler for decision edit."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import DecisionStatus

    # Extract data
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_edit button value: {button_value}")
        return

    decision_id = data.get("decision_id")
    expected_version = data.get("version")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    trigger_id = body["trigger_id"]

    async with get_connection() as conn:
        store = DecisionStore(conn)
        decision = await store.get(decision_id)

    if not decision:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Decision not found.",
        )
        return

    # Only allow editing proposed decisions
    if decision.status != DecisionStatus.PROPOSED:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Cannot edit a {decision.status.value} decision. Use 'Change' for approved decisions.",
        )
        return

    # Version check
    if expected_version and decision.version != expected_version:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"This decision has been modified. Please refresh and try again.",
        )
        return

    # Open edit modal
    modal = {
        "type": "modal",
        "callback_id": "decision_edit_modal",
        "private_metadata": json.dumps({
            "decision_id": decision_id,
            "channel_id": channel_id,
            "message_ts": body.get("message", {}).get("ts"),
        }),
        "title": {"type": "plain_text", "text": f"Edit DEC-{decision_id[:8]}"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
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
        ],
    }

    client.views_open(trigger_id=trigger_id, view=modal)


# =============================================================================
# Discard Decision
# =============================================================================


def handle_decision_discard(ack, body, client: WebClient):
    """Handle decision discard button click.

    Deletes a proposed decision (cannot discard approved decisions).
    Shows confirmation before discarding.
    """
    ack()
    _run_async(_handle_decision_discard_async(body, client))


async def _handle_decision_discard_async(body, client: WebClient):
    """Async handler for decision discard."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import DecisionStatus

    # Extract data
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_discard button value: {button_value}")
        return

    decision_id = data.get("decision_id")
    expected_version = data.get("version")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    message_ts = message.get("ts")

    async with get_connection() as conn:
        store = DecisionStore(conn)
        decision = await store.get(decision_id)

        if not decision:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Decision not found.",
            )
            return

        # Only allow discarding proposed decisions
        if decision.status != DecisionStatus.PROPOSED:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Cannot discard a {decision.status.value} decision. Use 'Deprecate' for approved decisions.",
            )
            return

        # Version check
        if expected_version and decision.version != expected_version:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"This decision has been modified. Please refresh and try again.",
            )
            return

        # Deprecate with discard reason (we don't delete, we mark as deprecated)
        await store.deprecate(
            decision_id=decision_id,
            deprecated_by=user_id,
            reason="Discarded before approval",
        )

    # Update message to show discarded state
    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"Decision DEC-{decision_id[:8]} discarded",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"~Decision DEC-{decision_id[:8]} discarded~",
                },
            },
        ],
    )

    logger.info(
        "Decision discarded",
        extra={
            "decision_id": decision_id,
            "discarded_by": user_id,
        }
    )


# =============================================================================
# Change Decision (creates new version)
# =============================================================================


def handle_decision_change(ack, body, client: WebClient):
    """Handle decision change button click.

    Opens modal to propose changes to an approved decision.
    Creates a new version when submitted.
    """
    ack()
    _run_async(_handle_decision_change_async(body, client))


async def _handle_decision_change_async(body, client: WebClient):
    """Async handler for decision change."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import DecisionStatus

    # Extract data
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_change button value: {button_value}")
        return

    decision_id = data.get("decision_id")
    expected_version = data.get("version")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    trigger_id = body["trigger_id"]

    async with get_connection() as conn:
        store = DecisionStore(conn)
        decision = await store.get(decision_id)

    if not decision:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Decision not found.",
        )
        return

    # Only allow changing approved decisions
    if decision.status == DecisionStatus.DEPRECATED:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Cannot change a deprecated decision.",
        )
        return

    # Version check
    if expected_version and decision.version != expected_version:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"This decision has been modified. Please refresh and try again.",
        )
        return

    # Open change modal
    modal = {
        "type": "modal",
        "callback_id": "decision_change_modal",
        "private_metadata": json.dumps({
            "decision_id": decision_id,
            "channel_id": channel_id,
            "message_ts": body.get("message", {}).get("ts"),
        }),
        "title": {"type": "plain_text", "text": f"Change DEC-{decision_id[:8]}"},
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
# Deprecate Decision
# =============================================================================


def handle_decision_deprecate(ack, body, client: WebClient):
    """Handle decision deprecate button click.

    Opens modal to deprecate an approved decision.
    """
    ack()
    _run_async(_handle_decision_deprecate_async(body, client))


async def _handle_decision_deprecate_async(body, client: WebClient):
    """Async handler for decision deprecation."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import DecisionStatus

    # Extract data
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_deprecate button value: {button_value}")
        return

    decision_id = data.get("decision_id")
    expected_version = data.get("version")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    trigger_id = body["trigger_id"]

    async with get_connection() as conn:
        store = DecisionStore(conn)
        decision = await store.get(decision_id)

    if not decision:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Decision not found.",
        )
        return

    if decision.status == DecisionStatus.DEPRECATED:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Decision is already deprecated.",
        )
        return

    # Version check
    if expected_version and decision.version != expected_version:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"This decision has been modified. Please refresh and try again.",
        )
        return

    # Open deprecation modal
    modal = {
        "type": "modal",
        "callback_id": "decision_deprecate_modal",
        "private_metadata": json.dumps({
            "decision_id": decision_id,
            "channel_id": channel_id,
            "message_ts": body.get("message", {}).get("ts"),
        }),
        "title": {"type": "plain_text", "text": f"Deprecate DEC-{decision_id[:8]}"},
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
# Modal Submissions
# =============================================================================


def handle_decision_edit_modal_submit(ack, body, client: WebClient):
    """Handle decision edit modal submission."""
    ack()
    _run_async(_handle_decision_edit_modal_submit_async(body, client))


async def _handle_decision_edit_modal_submit_async(body, client: WebClient):
    """Async handler for edit modal submission."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.slack.blocks.decision_cards import build_compact_draft_card

    view = body["view"]
    private_metadata = json.loads(view.get("private_metadata", "{}"))
    decision_id = private_metadata.get("decision_id")
    channel_id = private_metadata.get("channel_id")
    message_ts = private_metadata.get("message_ts")
    user_id = body["user"]["id"]

    # Extract values from modal
    values = view["state"]["values"]
    new_title = values["title_block"]["title_input"]["value"]
    new_description = values["description_block"]["description_input"]["value"]

    async with get_connection() as conn:
        store = DecisionStore(conn)
        decision = await store.update(
            decision_id=decision_id,
            title=new_title,
            description=new_description,
            changed_by=user_id,
            change_reason="Edited before approval",
        )

    # Update original message with new draft card
    blocks = build_compact_draft_card(decision)
    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        blocks=blocks,
        text=f"Decision DEC-{decision_id[:8]} updated",
    )

    logger.info(
        "Decision edited",
        extra={
            "decision_id": decision_id,
            "edited_by": user_id,
            "new_version": decision.version,
        }
    )


def handle_decision_change_modal_submit(ack, body, client: WebClient):
    """Handle decision change modal submission."""
    ack()
    _run_async(_handle_decision_change_modal_submit_async(body, client))


async def _handle_decision_change_modal_submit_async(body, client: WebClient):
    """Async handler for change modal submission."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.slack.blocks.decision_cards import build_approval_block

    view = body["view"]
    private_metadata = json.loads(view.get("private_metadata", "{}"))
    decision_id = private_metadata.get("decision_id")
    channel_id = private_metadata.get("channel_id")
    user_id = body["user"]["id"]

    # Extract values from modal
    values = view["state"]["values"]
    new_title = values["title_block"]["title_input"]["value"]
    new_description = values["description_block"]["description_input"]["value"]
    change_reason = values["reason_block"]["reason_input"]["value"]

    async with get_connection() as conn:
        store = DecisionStore(conn)
        decision = await store.update(
            decision_id=decision_id,
            title=new_title,
            description=new_description,
            changed_by=user_id,
            change_reason=change_reason,
        )

    # Post new version for approval
    blocks = build_approval_block(decision)
    client.chat_postMessage(
        channel=channel_id,
        blocks=blocks,
        text=f"Decision DEC-{decision_id[:8]} v{decision.version} proposed",
    )

    logger.info(
        "Decision change proposed",
        extra={
            "decision_id": decision_id,
            "changed_by": user_id,
            "new_version": decision.version,
            "reason": change_reason,
        }
    )


def handle_decision_deprecate_modal_submit(ack, body, client: WebClient):
    """Handle decision deprecate modal submission."""
    ack()
    _run_async(_handle_decision_deprecate_modal_submit_async(body, client))


async def _handle_decision_deprecate_modal_submit_async(body, client: WebClient):
    """Async handler for deprecate modal submission."""
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.slack.blocks.decision_cards import build_deprecated_decision_blocks

    view = body["view"]
    private_metadata = json.loads(view.get("private_metadata", "{}"))
    decision_id = private_metadata.get("decision_id")
    channel_id = private_metadata.get("channel_id")
    message_ts = private_metadata.get("message_ts")
    user_id = body["user"]["id"]

    # Extract values from modal
    values = view["state"]["values"]
    reason = values["reason_block"]["reason_input"]["value"]
    replacement_input = values["replacement_block"]["replacement_input"]["value"] or ""
    replacement_id = replacement_input.strip().upper().replace("DEC-", "") if replacement_input else None

    async with get_connection() as conn:
        store = DecisionStore(conn)

        # Validate replacement if provided
        replacement = None
        if replacement_id:
            # Try to find replacement decision
            decisions = await store.list_by_channel(channel_id, limit=100)
            for d in decisions:
                if d.id.startswith(replacement_id) or d.id[:8].upper() == replacement_id:
                    replacement = d
                    break

        decision = await store.deprecate(
            decision_id=decision_id,
            deprecated_by=user_id,
            reason=reason,
            replaced_by=replacement.id if replacement else None,
        )

    # Update original message with deprecated card
    blocks = build_deprecated_decision_blocks(decision, replacement)
    if message_ts:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=blocks,
            text=f"Decision DEC-{decision_id[:8]} deprecated",
        )
    else:
        client.chat_postMessage(
            channel=channel_id,
            blocks=blocks,
            text=f"Decision DEC-{decision_id[:8]} deprecated",
        )

    logger.info(
        "Decision deprecated",
        extra={
            "decision_id": decision_id,
            "deprecated_by": user_id,
            "reason": reason,
            "replaced_by": replacement.id if replacement else None,
        }
    )


# =============================================================================
# Registration helper
# =============================================================================


def register_decision_handlers(app):
    """Register all decision button handlers with the Slack app.

    Args:
        app: Slack Bolt App instance
    """
    # Button actions
    app.action("decision_approve")(handle_decision_approve)
    app.action("decision_edit")(handle_decision_edit)
    app.action("decision_discard")(handle_decision_discard)
    app.action("decision_change")(handle_decision_change)
    app.action("decision_deprecate")(handle_decision_deprecate)
    app.action("decision_history")(handle_decision_history)
    app.action("decision_view")(handle_decision_view)
    app.action("decision_cancel")(handle_decision_cancel)

    # Modal submissions
    app.view("decision_edit_modal")(handle_decision_edit_modal_submit)
    app.view("decision_change_modal")(handle_decision_change_modal_submit)
    app.view("decision_deprecate_modal")(handle_decision_deprecate_modal_submit)

    logger.info("Decision button handlers registered")
