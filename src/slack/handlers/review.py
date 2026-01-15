"""Review-to-ticket and scope gate handlers.

Handles turning review responses into Jira tickets.
"""

import json
import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def handle_review_to_ticket(ack, body, client: WebClient):
    """Handle "Turn into Jira ticket" button click from review response.

    Opens scope gate modal to let user choose what content becomes the ticket.
    Pattern: Sync wrapper with immediate ack.
    """
    ack()

    # Extract context from button value
    button_value = body["actions"][0].get("value", "{}")
    try:
        value = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse review_to_ticket button value: {button_value}")
        value = {}

    message = body.get("message", {})
    thread_ts = message.get("thread_ts") or message.get("ts")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]

    logger.info(
        "Review to ticket button clicked",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
        }
    )

    # Show scope gate modal
    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "review_scope_gate",
                "private_metadata": json.dumps({
                    "thread_ts": thread_ts,
                    "channel_id": channel_id,
                    "review_text": value.get("review_text", ""),
                    "topic": value.get("topic", ""),
                }),
                "title": {"type": "plain_text", "text": "Create Ticket"},
                "submit": {"type": "plain_text", "text": "Create Draft"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "*What should become a ticket?*"}
                    },
                    {
                        "type": "input",
                        "block_id": "scope_select",
                        "element": {
                            "type": "radio_buttons",
                            "action_id": "scope_choice",
                            "options": [
                                {"text": {"type": "plain_text", "text": "Final decision only"}, "value": "decision"},
                                {"text": {"type": "plain_text", "text": "Full review/proposal"}, "value": "full"},
                                {"text": {"type": "plain_text", "text": "Specific part (I'll describe)"}, "value": "custom"},
                            ],
                            "initial_option": {"text": {"type": "plain_text", "text": "Full review/proposal"}, "value": "full"},
                        },
                        "label": {"type": "plain_text", "text": "Scope"},
                    },
                    {
                        "type": "input",
                        "block_id": "custom_scope",
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "custom_input",
                            "placeholder": {"type": "plain_text", "text": "Describe what to include..."},
                        },
                        "label": {"type": "plain_text", "text": "Custom scope (if selected above)"},
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Failed to open scope gate modal: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Sorry, I couldn't open the scope selection. Please try again.",
        )


def handle_scope_gate_submit(ack, body, client: WebClient, view):
    """Handle scope gate modal submission.

    Creates a context message that triggers ticket flow with review content.
    Pattern: Sync wrapper delegates to async.
    """
    ack()
    _run_async(_handle_scope_gate_submit_async(body, client, view))


async def _handle_scope_gate_submit_async(body, client: WebClient, view):
    """Async handler for scope gate modal submission."""
    values = view["state"]["values"]
    private_metadata_raw = view.get("private_metadata", "{}")

    # Parse private metadata
    try:
        metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse scope gate private_metadata: {private_metadata_raw}")
        return

    scope = values["scope_select"]["scope_choice"]["selected_option"]["value"]
    custom_text = values.get("custom_scope", {}).get("custom_input", {}).get("value", "")

    channel_id = metadata.get("channel_id", "")
    thread_ts = metadata.get("thread_ts", "")
    review_text = metadata.get("review_text", "")
    topic = metadata.get("topic", "")

    logger.info(
        "Scope gate submitted",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "scope": scope,
        }
    )

    # Build context message for ticket extraction
    if scope == "decision":
        context_msg = f"Create a Jira ticket for the final decision from this review: {topic}"
    elif scope == "full":
        # Include review text for full context
        context_msg = f"Create a Jira ticket based on this review:\n\n{review_text[:1500]}"
    else:
        context_msg = f"Create a Jira ticket for: {custom_text}"

    # Post as user message to trigger ticket flow
    # The message handler will classify this as TICKET and proceed with extraction
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=context_msg,
    )
