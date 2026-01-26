"""Review initiation handlers.

Handles turning reviews into tickets - scope gate flow.
"""

import json
import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async
from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

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
    """Async handler for scope gate modal submission.

    Extracts items from review and routes to single or multi-ticket flow.
    """
    from src.slack.handlers.dispatch import _dispatch_result
    from src.schemas.state import UserIntent, WorkflowStep, PendingAction
    from src.graph.nodes.extraction import extract_multi_items_from_review
    from src.slack.blocks.multi_ticket import build_multi_ticket_preview_blocks

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

    # Get team_id from body
    team_id = body.get("team", {}).get("id") or body.get("user", {}).get("team_id", "")
    user_id = body.get("user", {}).get("id", "")

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

    # Post acknowledgment message
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="Analyzing review for ticket creation...",
    )

    # Extract items from review
    items = await extract_multi_items_from_review(review_text, scope, topic)

    if len(items) == 0:
        logger.warning(
            "No items extracted from review",
            extra={
                "channel": channel_id,
                "thread_ts": thread_ts,
                "topic": topic,
            }
        )
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="I couldn't identify any specific items to create. Please describe what you'd like to turn into tickets.",
        )
        return

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    if len(items) == 1:
        # Single-item flow - existing behavior
        runner = get_runner(identity)

        # Force TICKET intent and set the context message as user input
        forced_intent_result = {
            "intent": UserIntent.TICKET.value,
            "confidence": 1.0,
            "reasons": ["review_scope_gate: single item extracted from review"],
        }

        # Get current state and update with forced intent
        state = await runner._get_current_state()
        state["intent_result"] = forced_intent_result
        state["user_message"] = context_msg
        state["pending_action"] = None
        state["workflow_step"] = None

        await runner.graph.aupdate_state(runner._config, state)

        # Run graph with the context message
        try:
            result = await runner.run_with_message(context_msg, user_id)
            await _dispatch_result(result, identity, client, runner, tracker=None)
        except Exception as e:
            logger.error(f"Failed to create ticket from review: {e}", exc_info=True)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Sorry, I couldn't create the ticket. Please try again or create it manually.",
            )
    else:
        # Multi-item flow - show preview
        from src.slack.handlers.review.continue_ import show_multi_ticket_preview
        await show_multi_ticket_preview(items, identity, client, metadata)
