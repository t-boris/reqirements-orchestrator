"""Review-to-ticket, scope gate, and architecture approval handlers.

Handles turning review responses into Jira tickets and posting architecture decisions.
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


def handle_approve_architecture(ack, body, client: WebClient):
    """Handle "Approve & Post Decision" button click.

    Posts architecture decision to the main channel (not thread).
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_approve_architecture_async(body, client))


async def _handle_approve_architecture_async(body, client: WebClient):
    """Async handler for architecture approval."""
    from src.slack.blocks import build_decision_blocks

    # Extract context from button value
    button_value = body["actions"][0].get("value", "{}")
    try:
        value = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse approve_architecture button value: {button_value}")
        value = {}

    message = body.get("message", {})
    thread_ts = message.get("thread_ts") or message.get("ts")
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    team_id = body.get("team", {}).get("id", "")

    topic = value.get("topic", "Architecture Decision")
    persona = value.get("persona", "")

    logger.info(
        "Approve architecture button clicked",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "topic": topic,
        }
    )

    # Get review context from state
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )
    runner = get_runner(identity)
    state = await runner._get_current_state()
    review_context = state.get("review_context")

    if not review_context:
        # No review context - use message text as fallback
        message_text = message.get("text", "")
        review_summary = message_text[:1000] if message_text else "Architecture approved"
    else:
        review_summary = (
            review_context.get("updated_recommendation") or
            review_context.get("review_summary", "Architecture approved")
        )

    # Extract decision using LLM
    from src.llm import get_llm
    import re

    try:
        llm = get_llm()
        extraction_prompt = f'''Based on this architecture review, extract the decision:

Review: {review_summary[:2000]}

Return a JSON object:
{{
    "topic": "What was being decided (1 line)",
    "decision": "The chosen approach (1-2 sentences)"
}}

Be concise. This will be posted to the channel as a permanent record.
'''
        extraction_result = await llm.chat(extraction_prompt)

        # Parse JSON response
        json_match = re.search(r'\{[^{}]*\}', extraction_result, re.DOTALL)
        if json_match:
            decision_data = json.loads(json_match.group())
        else:
            decision_data = {"topic": topic, "decision": "Approved"}

        extracted_topic = decision_data.get("topic", topic)
        decision_text = decision_data.get("decision", "Approved")

        # Build and post decision blocks to CHANNEL (not thread!)
        decision_blocks = build_decision_blocks(
            topic=extracted_topic,
            decision=decision_text,
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
        )

        # Post to channel root (no thread_ts)
        client.chat_postMessage(
            channel=channel_id,
            blocks=decision_blocks,
            text=f"Architecture Decision: {extracted_topic}",
        )

        # Confirm in thread
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Decision recorded in channel.",
        )

        # Freeze review_context to review_artifact (Phase 20)
        if review_context:
            import hashlib
            from datetime import datetime, timezone
            from src.schemas.state import ReviewState

            review_context["state"] = ReviewState.POSTED

            review_artifact = {
                "kind": "architecture" if "architect" in persona.lower() else "security" if "security" in persona.lower() else "pm_review",
                "version": review_context.get("version", 1),
                "summary": review_context.get("review_summary", ""),
                "updated_summary": review_context.get("updated_recommendation"),
                "topic": extracted_topic,
                "persona": persona,
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "thread_ts": thread_ts,
                "channel_id": channel_id,
                "content_hash": hashlib.sha256(
                    (review_context.get("review_summary", "") +
                     (review_context.get("updated_recommendation") or "")).encode()
                ).hexdigest()[:16],
            }

            # Update state
            await runner._update_state({
                "review_artifact": review_artifact,
                "review_context": None,
            })

            logger.info(
                "Froze review_context to review_artifact via button",
                extra={
                    "topic": extracted_topic,
                    "content_hash": review_artifact["content_hash"],
                }
            )

    except Exception as e:
        logger.error(f"Failed to extract/post decision: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="I understood that as approval, but couldn't extract the decision. The review is still available above.",
        )
