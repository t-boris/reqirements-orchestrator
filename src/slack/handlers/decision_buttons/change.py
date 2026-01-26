"""Decision change and edit button handlers.

Handles editing proposed decisions and changing approved decisions.
Edit creates a new version of a proposed decision.
Change creates a new proposed version of an approved decision.

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
# Edit Decision (proposed only)
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

    # =========================================================================
    # STEP 1: Database state update (TRUTH) - must succeed first
    # =========================================================================
    async with get_connection() as conn:
        store = DecisionStore(conn)
        decision = await store.update(
            decision_id=decision_id,
            title=new_title,
            description=new_description,
            changed_by=user_id,
            change_reason="Edited before approval",
        )

    # =========================================================================
    # STEP 2: Slack message update (PRESENTATION) - best effort
    # =========================================================================
    try:
        blocks = build_compact_draft_card(decision)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=blocks,
            text=f"Decision DEC-{decision_id[:8]} updated",
        )
    except Exception as slack_err:
        # Slack message update failed, but decision is already updated
        logger.warning(
            "Slack message update failed, but decision is updated",
            extra={
                "decision_id": decision_id,
                "new_version": decision.version,
                "error": str(slack_err),
            }
        )

    logger.info(
        "Decision edited",
        extra={
            "decision_id": decision_id,
            "edited_by": user_id,
            "new_version": decision.version,
        }
    )


# =============================================================================
# Change Decision (creates new version of approved decision)
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

    # Truncate values for Slack modal limits (150 chars for plain_text_input)
    modal_title = decision.title[:147] + "..." if len(decision.title) > 150 else decision.title
    modal_desc = decision.description[:2997] + "..." if len(decision.description) > 3000 else decision.description

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
                    "initial_value": modal_title,
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
                    "initial_value": modal_desc,
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


def handle_decision_change_modal_submit(ack, body, client: WebClient):
    """Handle decision change modal submission."""
    ack()
    _run_async(_handle_decision_change_modal_submit_async(body, client))


async def _handle_decision_change_modal_submit_async(body, client: WebClient):
    """Async handler for change modal submission.

    Phase 41: Now creates DecisionChangeOp and shows impact preview before applying.
    If impact.has_jira_writes: post impact preview card for confirmation
    If no Jira writes: proceed with approval block as before
    """
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.db.decision_change_op_store import DecisionChangeOpStore
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.sync.impact_analysis import ImpactAnalysisService
    from src.schemas.decision import DecisionChangeOpType
    from src.slack.blocks.decision_cards import build_approval_block, build_impact_preview_card

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

    settings = get_settings()
    jira_service = JiraService(settings)

    try:
        async with get_connection() as conn:
            store = DecisionStore(conn)
            link_store = DecisionLinkStore(conn)
            op_store = DecisionChangeOpStore(conn)

            # Get current decision before update
            old_decision = await store.get(decision_id)
            from_version = old_decision.version if old_decision else 1

            # =====================================================================
            # STEP 1: Update decision in DB (TRUTH)
            # =====================================================================
            decision = await store.update(
                decision_id=decision_id,
                title=new_title,
                description=new_description,
                changed_by=user_id,
                change_reason=change_reason,
            )

            # =====================================================================
            # STEP 2: Create DecisionChangeOp and run impact analysis
            # =====================================================================
            op = await op_store.create(
                decision_id=decision_id,
                operation=DecisionChangeOpType.EDIT,
                from_version=from_version,
                to_version=decision.version,
                actor=user_id,
            )

            # Run impact analysis
            impact_service = ImpactAnalysisService(jira_service, link_store, store)
            impact = await impact_service.analyze(decision, DecisionChangeOpType.EDIT)

            # Store impact on operation
            await op_store.set_impact(op.id, impact)

        # =====================================================================
        # STEP 3: Post UI based on impact
        # =====================================================================
        try:
            if impact.has_jira_writes:
                # Show impact preview card for confirmation
                blocks = build_impact_preview_card(decision, op, impact)
                client.chat_postMessage(
                    channel=channel_id,
                    blocks=blocks,
                    text=f"Decision DEC-{decision_id[:8]} v{decision.version} - confirm changes",
                )
                logger.info(
                    "Decision change proposed with impact preview",
                    extra={
                        "decision_id": decision_id,
                        "op_id": op.id,
                        "changed_by": user_id,
                        "new_version": decision.version,
                        "has_jira_writes": True,
                        "total_affected": impact.total_affected,
                    }
                )
            else:
                # No Jira writes needed - auto-confirm and show approval block
                await op_store.confirm(op.id)
                from src.schemas.decision import DecisionChangeOpState
                await op_store.update_state(op.id, DecisionChangeOpState.APPLYING)
                await op_store.complete(op.id)

                blocks = build_approval_block(decision)
                client.chat_postMessage(
                    channel=channel_id,
                    blocks=blocks,
                    text=f"Decision DEC-{decision_id[:8]} v{decision.version} proposed",
                )
                logger.info(
                    "Decision change proposed (no Jira impact)",
                    extra={
                        "decision_id": decision_id,
                        "changed_by": user_id,
                        "new_version": decision.version,
                        "reason": change_reason,
                    }
                )
        except Exception as slack_err:
            logger.warning(
                "Slack message failed, but decision change is recorded",
                extra={
                    "decision_id": decision_id,
                    "new_version": decision.version,
                    "error": str(slack_err),
                }
            )

    except Exception as e:
        logger.error(f"Failed to process decision change: {e}", exc_info=True)
    finally:
        await jira_service.close()
