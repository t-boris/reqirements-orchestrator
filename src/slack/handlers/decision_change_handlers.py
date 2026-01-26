"""Decision change confirmation button handlers.

Phase 41: Decision Change Propagation - Confirmation UI

Handles confirmation buttons from the impact preview card:
- decision_change_apply: Confirm and apply to DB + Slack + Jira
- decision_change_slack_only: Apply to DB + Slack only (skip Jira)
- decision_change_cancel: Cancel the operation

INVARIANT I2: Slack = UI
Handlers follow truth-first ordering:
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
# Apply Decision Change (with Jira)
# =============================================================================


def handle_decision_change_apply(ack, body, client: WebClient):
    """Handle "Apply updates" button click.

    Confirms the operation and applies changes to DB + Slack + Jira.
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_decision_change_apply_async(body, client))


async def _handle_decision_change_apply_async(body, client: WebClient):
    """Async handler for applying decision change with Jira sync.

    CRITICAL ORDER:
    1. Confirm operation state (TRUTH)
    2. Jira sync will be handled by Plan 41-04 (DecisionChangeExecutor)
    3. Update Slack message (PRESENTATION - best effort)
    """
    from src.db.connection import get_connection
    from src.db.decision_change_op_store import DecisionChangeOpStore
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import DecisionChangeOpState

    # Extract data from button
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_change_apply button value: {button_value}")
        return

    op_id = data.get("op_id")
    decision_id = data.get("decision_id")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    message_ts = message.get("ts")

    logger.info(
        "Decision change apply button clicked",
        extra={
            "op_id": op_id,
            "decision_id": decision_id,
            "user_id": user_id,
        }
    )

    try:
        async with get_connection() as conn:
            op_store = DecisionChangeOpStore(conn)
            decision_store = DecisionStore(conn)

            # Get operation
            op = await op_store.get(op_id)
            if not op:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text="Operation not found or already processed.",
                )
                return

            # Check state - must be PROPOSED
            if op.state != DecisionChangeOpState.PROPOSED:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"Operation already {op.state.value}.",
                )
                return

            # Get decision for display
            decision = await decision_store.get(decision_id)

            # =================================================================
            # STEP 1: Confirm operation (TRUTH)
            # =================================================================
            await op_store.confirm(op_id)

            # =================================================================
            # STEP 2: Execution will be handled by Plan 41-04
            # For now, update message to show confirmed state
            # =================================================================

        # =====================================================================
        # STEP 3: Slack message (PRESENTATION) - best effort
        # =====================================================================
        try:
            decision_title = decision.title if decision else "Decision"
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=[{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{decision_title}*\n\nOperation confirmed. Applying changes..."
                    }
                }],
                text="Applying changes...",
            )
        except Exception as slack_err:
            logger.warning(
                "Slack message update failed, but operation is confirmed",
                extra={
                    "op_id": op_id,
                    "decision_id": decision_id,
                    "error": str(slack_err),
                }
            )

        logger.info(
            "Decision change operation confirmed (apply with Jira)",
            extra={
                "op_id": op_id,
                "decision_id": decision_id,
                "user_id": user_id,
            }
        )

    except ValueError as e:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to apply decision change: {e}", exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Failed to apply decision change: {str(e)}",
        )


# =============================================================================
# Apply Decision Change (Slack only, skip Jira)
# =============================================================================


def handle_decision_change_slack_only(ack, body, client: WebClient):
    """Handle "Apply to Slack only" button click.

    Confirms the operation but skips Jira sync.
    User wants to manually update Jira.
    """
    ack()
    _run_async(_handle_decision_change_slack_only_async(body, client))


async def _handle_decision_change_slack_only_async(body, client: WebClient):
    """Async handler for applying decision change without Jira sync.

    Marks operation as confirmed but with skip_jira flag.
    Plan 41-04 will check this flag and skip Jira writes.
    """
    from src.db.connection import get_connection
    from src.db.decision_change_op_store import DecisionChangeOpStore
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import DecisionChangeOpState

    # Extract data from button
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_change_slack_only button value: {button_value}")
        return

    op_id = data.get("op_id")
    decision_id = data.get("decision_id")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    message_ts = message.get("ts")

    logger.info(
        "Decision change slack-only button clicked",
        extra={
            "op_id": op_id,
            "decision_id": decision_id,
            "user_id": user_id,
        }
    )

    try:
        async with get_connection() as conn:
            op_store = DecisionChangeOpStore(conn)
            decision_store = DecisionStore(conn)

            # Get operation
            op = await op_store.get(op_id)
            if not op:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text="Operation not found or already processed.",
                )
                return

            # Check state - must be PROPOSED
            if op.state != DecisionChangeOpState.PROPOSED:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"Operation already {op.state.value}.",
                )
                return

            # Get decision for display
            decision = await decision_store.get(decision_id)

            # =================================================================
            # STEP 1: Confirm operation (TRUTH)
            # Note: Plan 41-04 will need a way to know skip_jira
            # For now, we confirm and the executor will handle it
            # =================================================================
            await op_store.confirm(op_id)

            # Mark as DONE immediately since we're skipping Jira
            # This is a simplified path - full executor in Plan 41-04
            await op_store.update_state(op_id, DecisionChangeOpState.APPLYING)
            await op_store.complete(op_id)

        # =====================================================================
        # STEP 2: Slack message (PRESENTATION) - best effort
        # =====================================================================
        try:
            decision_title = decision.title if decision else "Decision"
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=[{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{decision_title}*\n\nChanges applied to Slack. Jira was not updated - you may want to update it manually."
                    }
                }],
                text="Changes applied (Slack only)",
            )
        except Exception as slack_err:
            logger.warning(
                "Slack message update failed, but operation is complete",
                extra={
                    "op_id": op_id,
                    "decision_id": decision_id,
                    "error": str(slack_err),
                }
            )

        logger.info(
            "Decision change operation confirmed (Slack only)",
            extra={
                "op_id": op_id,
                "decision_id": decision_id,
                "user_id": user_id,
            }
        )

    except ValueError as e:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to apply decision change (Slack only): {e}", exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Failed to apply decision change: {str(e)}",
        )


# =============================================================================
# Cancel Decision Change
# =============================================================================


def handle_decision_change_cancel(ack, body, client: WebClient):
    """Handle "Cancel" button click.

    Cancels the pending operation.
    """
    ack()
    _run_async(_handle_decision_change_cancel_async(body, client))


async def _handle_decision_change_cancel_async(body, client: WebClient):
    """Async handler for cancelling decision change operation."""
    from src.db.connection import get_connection
    from src.db.decision_change_op_store import DecisionChangeOpStore
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import DecisionChangeOpState

    # Extract data from button
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_change_cancel button value: {button_value}")
        return

    op_id = data.get("op_id")
    decision_id = data.get("decision_id")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    message_ts = message.get("ts")

    logger.info(
        "Decision change cancel button clicked",
        extra={
            "op_id": op_id,
            "decision_id": decision_id,
            "user_id": user_id,
        }
    )

    try:
        async with get_connection() as conn:
            op_store = DecisionChangeOpStore(conn)
            decision_store = DecisionStore(conn)

            # Get operation
            op = await op_store.get(op_id)
            if not op:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text="Operation not found or already processed.",
                )
                return

            # Check if cancellable
            if op.state in (DecisionChangeOpState.DONE, DecisionChangeOpState.CANCELLED):
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"Operation already {op.state.value}.",
                )
                return

            # Get decision for display
            decision = await decision_store.get(decision_id)

            # =================================================================
            # Cancel operation (TRUTH)
            # =================================================================
            await op_store.cancel(op_id)

        # =====================================================================
        # Slack message (PRESENTATION) - best effort
        # =====================================================================
        try:
            decision_title = decision.title if decision else "Decision"
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=[{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"~*{decision_title}*~\n\n_Operation cancelled_"
                    }
                }],
                text="Operation cancelled",
            )
        except Exception as slack_err:
            logger.warning(
                "Slack message update failed, but operation is cancelled",
                extra={
                    "op_id": op_id,
                    "decision_id": decision_id,
                    "error": str(slack_err),
                }
            )

        logger.info(
            "Decision change operation cancelled",
            extra={
                "op_id": op_id,
                "decision_id": decision_id,
                "user_id": user_id,
            }
        )

    except ValueError as e:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to cancel decision change: {e}", exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Failed to cancel decision change: {str(e)}",
        )


# =============================================================================
# Registration helper
# =============================================================================


def register_decision_change_handlers(app):
    """Register decision change confirmation handlers.

    Args:
        app: Slack Bolt App instance
    """
    app.action("decision_change_apply")(handle_decision_change_apply)
    app.action("decision_change_slack_only")(handle_decision_change_slack_only)
    app.action("decision_change_cancel")(handle_decision_change_cancel)

    logger.info("Decision change confirmation handlers registered")
