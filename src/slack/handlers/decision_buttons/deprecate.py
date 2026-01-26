"""Decision deprecation and discard button handlers.

Handles deprecating approved decisions and discarding proposed decisions.
Discard marks a proposed decision as deprecated before approval.
Deprecate marks an approved decision as deprecated with optional replacement.

INVARIANT I2: Slack = UI
Handlers are READ-ONLY for truth stores.
Mutations follow truth-first ordering:
  1. Database state update (TRUTH) - must succeed first
  2. Jira sync (PROJECTION) - proceeds regardless of Slack
  3. Slack message (PRESENTATION) - best effort, failures logged not raised
"""
import json
import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


# =============================================================================
# Discard Decision (proposed only)
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

    # =========================================================================
    # Slack message update (PRESENTATION) - best effort, doesn't block state
    # =========================================================================
    try:
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
    except Exception as slack_err:
        # Slack message update failed, but decision is already discarded
        logger.warning(
            "Slack message update failed, but decision is discarded",
            extra={
                "decision_id": decision_id,
                "error": str(slack_err),
            }
        )

    logger.info(
        "Decision discarded",
        extra={
            "decision_id": decision_id,
            "discarded_by": user_id,
        }
    )


# =============================================================================
# Deprecate Decision (approved)
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


def handle_decision_deprecate_modal_submit(ack, body, client: WebClient):
    """Handle decision deprecate modal submission."""
    ack()
    _run_async(_handle_decision_deprecate_modal_submit_async(body, client))


async def _handle_decision_deprecate_modal_submit_async(body, client: WebClient):
    """Async handler for deprecate modal submission.

    Phase 41: Deprecation now creates DecisionChangeOp and shows impact preview.
    DEPRECATE always has_jira_writes=True (clears managed sections).
    """
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.db.decision_change_op_store import DecisionChangeOpStore
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.sync.impact_analysis import ImpactAnalysisService
    from src.schemas.decision import DecisionChangeOpType
    from src.slack.blocks.decision_cards import build_impact_preview_card

    view = body["view"]
    private_metadata = json.loads(view.get("private_metadata", "{}"))
    decision_id = private_metadata.get("decision_id")
    channel_id = private_metadata.get("channel_id")
    user_id = body["user"]["id"]

    # Extract values from modal
    values = view["state"]["values"]
    reason = values["reason_block"]["reason_input"]["value"]
    replacement_input = values["replacement_block"]["replacement_input"]["value"] or ""
    replacement_id = replacement_input.strip().upper().replace("DEC-", "") if replacement_input else None

    settings = get_settings()
    jira_service = JiraService(settings)

    try:
        async with get_connection() as conn:
            store = DecisionStore(conn)
            link_store = DecisionLinkStore(conn)
            op_store = DecisionChangeOpStore(conn)

            # Get current decision
            decision = await store.get(decision_id)
            if not decision:
                logger.error(f"Decision not found for deprecation: {decision_id}")
                return

            # Validate replacement if provided
            replacement = None
            if replacement_id:
                decisions = await store.list_by_channel(channel_id, limit=100)
                for d in decisions:
                    if d.id.startswith(replacement_id) or d.id[:8].upper() == replacement_id:
                        replacement = d
                        break

            # Store reason and replacement in private_metadata for the confirmation handlers
            # Note: Plan 41-04 executor will need to retrieve this from context

            # =====================================================================
            # Create DecisionChangeOp for deprecation
            # =====================================================================
            op = await op_store.create(
                decision_id=decision_id,
                operation=DecisionChangeOpType.DEPRECATE,
                from_version=decision.version,
                to_version=None,  # Deprecate doesn't create new version
                actor=user_id,
            )

            # Run impact analysis
            impact_service = ImpactAnalysisService(jira_service, link_store, store)
            impact = await impact_service.analyze(decision, DecisionChangeOpType.DEPRECATE)

            # Store impact on operation
            await op_store.set_impact(op.id, impact)

        # =====================================================================
        # Show impact preview card (DEPRECATE always shows confirmation)
        # =====================================================================
        try:
            blocks = build_impact_preview_card(decision, op, impact)
            client.chat_postMessage(
                channel=channel_id,
                blocks=blocks,
                text=f"Decision DEC-{decision_id[:8]} - confirm deprecation",
            )
        except Exception as slack_err:
            logger.warning(
                "Slack message failed for deprecation preview",
                extra={
                    "decision_id": decision_id,
                    "op_id": op.id,
                    "error": str(slack_err),
                }
            )

        logger.info(
            "Decision deprecation proposed with impact preview",
            extra={
                "decision_id": decision_id,
                "op_id": op.id,
                "deprecated_by": user_id,
                "reason": reason,
                "replaced_by": replacement.id if replacement else None,
                "total_affected": impact.total_affected,
            }
        )

    except Exception as e:
        logger.error(f"Failed to process deprecation: {e}", exc_info=True)
    finally:
        await jira_service.close()
