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

    CRITICAL ORDER (Phase 41-04 DecisionChangeExecutor):
    1. Confirm operation state (TRUTH)
    2. Execute via DecisionChangeExecutor: DB -> Slack -> Jira
    3. Show result card (PRESENTATION)
    """
    from src.config.settings import get_settings
    from src.db.connection import get_connection
    from src.db.decision_change_op_store import DecisionChangeOpStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.db.decision_store import DecisionStore
    from src.jira.client import JiraService
    from src.schemas.decision import DecisionChangeOpState
    from src.slack.blocks.decision_cards import build_change_result_card
    from src.sync.decision_change_executor import DecisionChangeExecutor

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

    settings = get_settings()
    jira_service = JiraService(settings)

    try:
        async with get_connection() as conn:
            op_store = DecisionChangeOpStore(conn)
            decision_store = DecisionStore(conn)
            link_store = DecisionLinkStore(conn)

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

            # =================================================================
            # STEP 1: Confirm operation (TRUTH)
            # =================================================================
            await op_store.confirm(op_id)

            # =================================================================
            # STEP 2: Execute via DecisionChangeExecutor
            # =================================================================
            executor = DecisionChangeExecutor(
                decision_store=decision_store,
                op_store=op_store,
                link_store=link_store,
                jira_service=jira_service,
                slack_client=client,
            )
            result = await executor.execute(op_id, skip_jira=False)

            # Get updated decision and op for result card
            op = await op_store.get(op_id)
            decision = await decision_store.get(decision_id)

        # =====================================================================
        # STEP 3: Show result card (PRESENTATION)
        # =====================================================================
        try:
            if decision and op:
                result_blocks = build_change_result_card(decision, op, result)
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    blocks=result_blocks,
                    text="Decision change complete" if result.success else "Decision change completed with errors",
                )
            else:
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text="Decision change complete" if result.success else "Decision change completed with errors",
                )
        except Exception as slack_err:
            logger.warning(
                "Slack result card update failed",
                extra={
                    "op_id": op_id,
                    "decision_id": decision_id,
                    "error": str(slack_err),
                }
            )

        logger.info(
            "Decision change operation completed",
            extra={
                "op_id": op_id,
                "decision_id": decision_id,
                "user_id": user_id,
                "success": result.success,
                "jira_updated": result.jira_updated,
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
    finally:
        await jira_service.close()


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

    Same as apply handler but passes skip_jira=True to executor.
    Phase 41-04: DecisionChangeExecutor handles truth-first ordering.
    """
    from src.config.settings import get_settings
    from src.db.connection import get_connection
    from src.db.decision_change_op_store import DecisionChangeOpStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.db.decision_store import DecisionStore
    from src.jira.client import JiraService
    from src.schemas.decision import DecisionChangeOpState
    from src.slack.blocks.decision_cards import build_change_result_card
    from src.sync.decision_change_executor import DecisionChangeExecutor

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

    settings = get_settings()
    jira_service = JiraService(settings)

    try:
        async with get_connection() as conn:
            op_store = DecisionChangeOpStore(conn)
            decision_store = DecisionStore(conn)
            link_store = DecisionLinkStore(conn)

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

            # =================================================================
            # STEP 1: Confirm operation (TRUTH)
            # =================================================================
            await op_store.confirm(op_id)

            # =================================================================
            # STEP 2: Execute via DecisionChangeExecutor with skip_jira=True
            # =================================================================
            executor = DecisionChangeExecutor(
                decision_store=decision_store,
                op_store=op_store,
                link_store=link_store,
                jira_service=jira_service,
                slack_client=client,
            )
            result = await executor.execute(op_id, skip_jira=True)

            # Get updated decision and op for result card
            op = await op_store.get(op_id)
            decision = await decision_store.get(decision_id)

        # =====================================================================
        # STEP 3: Show result card (PRESENTATION)
        # =====================================================================
        try:
            if decision and op:
                result_blocks = build_change_result_card(decision, op, result)
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    blocks=result_blocks,
                    text="Decision change complete (Slack only)",
                )
            else:
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text="Decision change complete (Slack only)",
                )
        except Exception as slack_err:
            logger.warning(
                "Slack result card update failed",
                extra={
                    "op_id": op_id,
                    "decision_id": decision_id,
                    "error": str(slack_err),
                }
            )

        logger.info(
            "Decision change operation completed (Slack only)",
            extra={
                "op_id": op_id,
                "decision_id": decision_id,
                "user_id": user_id,
                "success": result.success,
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
    finally:
        await jira_service.close()


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
# Retry Failed Tickets
# =============================================================================


def handle_decision_change_retry(ack, body, client: WebClient):
    """Handle "Retry failed" button click.

    Retries failed ticket syncs from a previous execution.
    """
    ack()
    _run_async(_handle_decision_change_retry_async(body, client))


async def _handle_decision_change_retry_async(body, client: WebClient):
    """Async handler for retrying failed ticket syncs.

    Uses DecisionChangeExecutor.retry_failed_tickets() to retry.
    """
    from src.config.settings import get_settings
    from src.db.connection import get_connection
    from src.db.decision_change_op_store import DecisionChangeOpStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.db.decision_store import DecisionStore
    from src.jira.client import JiraService
    from src.slack.blocks.decision_cards import build_change_result_card
    from src.sync.decision_change_executor import DecisionChangeExecutor

    # Extract data from button
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_change_retry button value: {button_value}")
        return

    op_id = data.get("op_id")
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message = body.get("message", {})
    message_ts = message.get("ts")

    logger.info(
        "Decision change retry button clicked",
        extra={"op_id": op_id, "user_id": user_id}
    )

    settings = get_settings()
    jira_service = JiraService(settings)

    try:
        async with get_connection() as conn:
            op_store = DecisionChangeOpStore(conn)
            decision_store = DecisionStore(conn)
            link_store = DecisionLinkStore(conn)

            # Execute retry
            executor = DecisionChangeExecutor(
                decision_store=decision_store,
                op_store=op_store,
                link_store=link_store,
                jira_service=jira_service,
                slack_client=client,
            )
            result = await executor.retry_failed_tickets(op_id)

            # Get updated decision and op for result card
            op = await op_store.get(op_id)
            decision = await decision_store.get(result.decision_id) if result.decision_id else None

        # Show updated result card
        try:
            if decision and op:
                result_blocks = build_change_result_card(decision, op, result)
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    blocks=result_blocks,
                    text="Retry complete" if result.success else "Retry completed with errors",
                )
        except Exception as slack_err:
            logger.warning(
                "Slack result card update failed after retry",
                extra={"op_id": op_id, "error": str(slack_err)}
            )

        logger.info(
            "Decision change retry completed",
            extra={
                "op_id": op_id,
                "success": result.success,
                "updated": result.updated_count,
                "failed": result.failed_count,
            }
        )

    except Exception as e:
        logger.error(f"Failed to retry decision change: {e}", exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Failed to retry: {str(e)}",
        )
    finally:
        await jira_service.close()


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
    app.action("decision_change_retry")(handle_decision_change_retry)

    logger.info("Decision change confirmation handlers registered")
