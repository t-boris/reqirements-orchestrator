"""Architecture approval handler.

Handles posting architecture decisions to the main channel.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async
from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

logger = logging.getLogger(__name__)


def handle_approve_architecture(ack, body, client: WebClient):
    """Handle "Approve & Post Decision" button click.

    Posts architecture decision to the main channel (not thread).
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_approve_architecture_async(body, client))


async def _handle_approve_architecture_async(body, client: WebClient):
    """Async handler for architecture approval."""
    from src.slack.handlers.review.decision_core import (
        extract_decisions_from_text,
        create_and_post_decisions,
        record_decisions_for_sync,
    )
    from src.schemas.state import ReviewState

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

    # Show progress indicator immediately
    progress_msg = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=":hourglass_flowing_sand: Posting decisions to channel...",
    )

    logger.info(
        "Approve architecture button clicked",
        extra={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "topic": topic,
        }
    )

    try:
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

        # Extract ALL decisions using shared LLM extraction
        decisions = await extract_decisions_from_text(review_summary, max_length=3000)

        # Use fallback if no decisions extracted
        if not decisions:
            decisions = [{"topic": topic, "decision": review_summary[:500]}]

        logger.info(
            f"Extracted {len(decisions)} decision(s) from review",
            extra={"channel_id": channel_id, "decision_count": len(decisions)},
        )

        # Create and post decisions using shared logic
        result = await create_and_post_decisions(
            client=client,
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            decisions=decisions,
            persona=persona,
            check_conflicts=True,
            fallback_topic=topic,
            fallback_text=review_summary,
        )

        # Confirm in thread
        if result.decisions_created == 1:
            confirm_msg = "Decision recorded in channel."
        else:
            confirm_msg = f"{result.decisions_created} decisions recorded in channel."
        if result.conflicts:
            confirm_msg += " Check conflict warning above."

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=confirm_msg,
        )

        # Freeze review_context to review_artifact
        primary_topic = decisions[0].get("topic", topic) if decisions else topic
        if review_context:
            review_context["state"] = ReviewState.POSTED

            review_artifact = {
                "kind": "architecture" if "architect" in persona.lower() else "security" if "security" in persona.lower() else "pm_review",
                "version": review_context.get("version", 1),
                "summary": review_context.get("review_summary", ""),
                "updated_summary": review_context.get("updated_recommendation"),
                "topic": primary_topic,
                "decisions": decisions,
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
                    "topic": primary_topic,
                    "decision_count": result.decisions_created,
                    "content_hash": review_artifact["content_hash"],
                }
            )

        # Record ALL decisions for sync tracking
        await record_decisions_for_sync(
            channel_id=channel_id,
            thread_ts=thread_ts,
            decisions=decisions,
            fallback_topic=topic,
        )

        # Delete progress message after completion
        try:
            client.chat_delete(
                channel=channel_id,
                ts=progress_msg["ts"],
            )
        except Exception as del_err:
            logger.debug(f"Could not delete progress message: {del_err}")

    except Exception as e:
        logger.error(f"Failed to extract/post decision: {e}", exc_info=True)
        # Delete progress message on error
        try:
            client.chat_delete(
                channel=channel_id,
                ts=progress_msg["ts"],
            )
        except Exception:
            pass
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="I understood that as approval, but couldn't extract the decision. The review is still available above.",
        )
