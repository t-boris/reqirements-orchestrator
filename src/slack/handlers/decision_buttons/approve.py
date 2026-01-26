"""Decision approval button handlers.

INVARIANT I2: Slack = UI
Handlers are READ-ONLY for truth stores.
Mutations go through graph dispatch or follow truth-first ordering:
  1. Database state update (TRUTH) - must succeed first
  2. Jira sync (PROJECTION) - proceeds regardless of Slack
  3. Slack message (PRESENTATION) - best effort, failures logged not raised
Message failures NEVER block state updates.
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
