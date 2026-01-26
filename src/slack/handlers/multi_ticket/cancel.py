"""Cancel handlers for multi-ticket workflow.

Handles:
- Cancel button click
- Cancel confirmation modal
"""
import json
import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async
from src.graph.runner import get_runner
from src.slack.session import SessionIdentity

logger = logging.getLogger(__name__)


def handle_multi_ticket_cancel(ack, body: dict, client: WebClient) -> None:
    """Handle cancel button click.

    Cancels multi-ticket creation and clears state.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_cancel_async(body, client))


async def _handle_multi_ticket_cancel_async(body: dict, client: WebClient) -> None:
    """Cancel multi-ticket creation.

    If user has made edits, show confirmation modal before cancelling.
    Otherwise, proceed with direct cancel.
    """
    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts
    team_id = body.get("team", {}).get("id", "unknown")
    user_id = body.get("user", {}).get("id")
    trigger_id = body.get("trigger_id")

    if not channel_id or not message_ts:
        logger.warning("Missing channel_id or message_ts in cancel body")
        return

    logger.info(
        "Multi-ticket cancel requested",
        extra={
            "channel": channel_id,
            "message_ts": message_ts,
            "user_id": user_id,
        },
    )

    # Check if any edits were made
    identity = SessionIdentity(team_id=team_id, channel_id=channel_id, thread_ts=thread_ts)
    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for cancel: {e}", exc_info=True)
        # Proceed with cancel anyway
        await _do_cancel(client, channel_id, message_ts, thread_ts, None)
        return

    multi_state = state.get("multi_ticket_state", {})
    has_edits = multi_state.get("has_edits", False)

    if has_edits and trigger_id:
        # Show confirmation modal
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "multi_ticket_cancel_confirm",
                "title": {"type": "plain_text", "text": "Discard Changes?"},
                "submit": {"type": "plain_text", "text": "Discard"},
                "close": {"type": "plain_text", "text": "Keep Editing"},
                "private_metadata": json.dumps({
                    "message_ts": message_ts,
                    "thread_ts": thread_ts,
                    "channel_id": channel_id,
                }),
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "You've made changes to the items. Are you sure you want to discard them?",
                        },
                    },
                ],
            },
        )
    else:
        # Direct cancel
        await _do_cancel(client, channel_id, message_ts, thread_ts, runner)


async def _do_cancel(
    client: WebClient,
    channel_id: str,
    message_ts: str,
    thread_ts: str,
    runner,
) -> None:
    """Execute the cancel action.

    Args:
        client: Slack WebClient
        channel_id: Channel ID
        message_ts: Preview message timestamp to delete
        thread_ts: Thread timestamp for reply
        runner: Graph runner (optional) to clear state
    """
    # Delete preview message
    try:
        client.chat_delete(channel=channel_id, ts=message_ts)
    except Exception as e:
        logger.warning(f"Failed to delete preview message: {e}")
        # Fall back to updating the message
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Multi-ticket creation cancelled.",
            blocks=[],
        )

    # Post dismissal
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="Multi-ticket creation cancelled.",
    )

    # Clear state
    if runner:
        try:
            await runner.update_state({"multi_ticket_state": None})
        except Exception as e:
            logger.warning(f"Failed to clear multi_ticket_state: {e}")

    logger.info(
        "Multi-ticket creation cancelled",
        extra={"channel_id": channel_id},
    )


def handle_multi_ticket_cancel_confirm(ack, body, client: WebClient, view) -> None:
    """Handle cancel confirmation modal submission.

    Args:
        ack: Slack ack function
        body: Slack view submission body
        client: Slack WebClient
        view: Slack view object
    """
    ack()
    _run_async(_handle_multi_ticket_cancel_confirm_async(body, client, view))


async def _handle_multi_ticket_cancel_confirm_async(body, client: WebClient, view) -> None:
    """Execute cancel after confirmation."""
    private_metadata_raw = view.get("private_metadata", "{}")
    try:
        private_metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse private_metadata: {private_metadata_raw}")
        return

    message_ts = private_metadata.get("message_ts", "")
    thread_ts = private_metadata.get("thread_ts", "")
    channel_id = private_metadata.get("channel_id", "")

    if not channel_id or not message_ts:
        logger.warning("Missing channel_id or message_ts in cancel confirm")
        return

    # Get runner to clear state
    team_id = body.get("team", {}).get("id", "unknown")
    identity = SessionIdentity(team_id=team_id, channel_id=channel_id, thread_ts=thread_ts)

    runner = None
    try:
        runner = get_runner(identity)
    except Exception as e:
        logger.warning(f"Failed to get runner for cancel confirm: {e}")

    await _do_cancel(client, channel_id, message_ts, thread_ts, runner)
