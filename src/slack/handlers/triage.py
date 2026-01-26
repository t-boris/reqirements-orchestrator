"""Slack handlers for triage question answers.

Phase 44: Questions-First Collection Stage

Processes button clicks for triage questions. When triage is complete,
re-invokes the intent classification with enriched context.
"""
import json
import logging
import re
from typing import TYPE_CHECKING

from slack_bolt import Ack, App
from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def register_triage_handlers(app: App) -> None:
    """Register triage question handlers.

    Registers handlers for triage button clicks with pattern "triage_answer_*".
    """

    @app.action(re.compile(r"^triage_answer_.*"))
    def handle_triage_button(ack: Ack, body: dict, client: WebClient, action: dict):
        """Handle triage question button click (sync wrapper)."""
        ack()

        channel_id = body.get("channel", {}).get("id", "")
        message_ts = body.get("message", {}).get("ts")
        thread_ts = body.get("message", {}).get("thread_ts") or message_ts
        user_id = body.get("user", {}).get("id", "")
        value = action.get("value", "")

        _run_async(
            handle_triage_answer(
                body=body,
                client=client,
                action_id=action.get("action_id", ""),
                value=value,
                channel_id=channel_id,
                thread_ts=thread_ts,
                user_id=user_id,
                message_ts=message_ts,
            )
        )

    logger.info("Registered triage button handlers")


async def handle_triage_answer(
    body: dict,
    client: WebClient,
    action_id: str,
    value: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    message_ts: str | None = None,
) -> None:
    """Handle triage question button click.

    Flow:
    1. Parse button value (JSON)
    2. Save to TriageStore
    3. Check if more triage questions needed
    4. If complete: re-invoke intent router with enriched context
    5. If more needed: post next question

    Args:
        body: Full Slack interaction payload.
        client: Slack WebClient.
        action_id: Button action ID.
        value: JSON-encoded button value.
        channel_id: Slack channel ID.
        thread_ts: Thread timestamp.
        user_id: User who clicked.
        message_ts: Original message timestamp (for updating).
    """
    from src.db.connection import get_connection
    from src.db.triage_store import TriageStore
    from src.config.settings import get_settings
    from src.slack.session import SessionIdentity
    from src.graph.runner import get_runner
    from src.questions.triage_provider import TriageProvider
    from src.graph.triage_gate import check_triage_needed
    from src.slack.blocks.triage import build_triage_question_blocks
    from src.schemas.triage import TriageGap

    try:
        # Parse button value
        button_data = json.loads(value)
        question_id = button_data.get("question_id", "")
        target_field = button_data.get("target_field", "")
        answer_value = button_data.get("value", "")
        # Note: thread_ts from button_data should match the function arg

        logger.info(
            "Triage answer received",
            extra={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "target_field": target_field,
                "answer_value": answer_value,
            },
        )

        # Update the original message to show the selected answer
        if message_ts:
            try:
                # Find the label for the selected value
                label = answer_value
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text=f"Selected: *{label}*",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"Selected: *{label}*",
                            },
                        },
                    ],
                )
            except Exception as e:
                logger.warning(f"Could not update triage question message: {e}")

        # Save answer to TriageStore
        async with get_connection() as conn:
            store = TriageStore(conn)
            updated_answers = await store.update_field(
                channel_id=channel_id,
                thread_ts=thread_ts,
                field=target_field,
                value=answer_value,
            )

        logger.info(
            "Triage answer saved",
            extra={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "field": target_field,
                "value": answer_value,
            },
        )

        # Get runner to access state
        settings = get_settings()
        team_id = getattr(settings, "slack_team_id", "")

        identity = SessionIdentity(
            team_id=team_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )

        runner = get_runner(identity)
        state = await runner._get_current_state()

        # Update state with triage answers
        state["triage_answers"] = updated_answers
        await runner._update_state({"triage_answers": updated_answers})

        # Get the original message from state for re-classification
        user_message = state.get("user_message", "")
        if not user_message:
            # Try to get from messages
            messages = state.get("messages", [])
            if messages:
                last_human = None
                for msg in reversed(messages):
                    if hasattr(msg, "type") and msg.type == "human":
                        last_human = msg
                        break
                    elif hasattr(msg, "content") and not hasattr(msg, "type"):
                        last_human = msg
                        break
                if last_human:
                    user_message = getattr(last_human, "content", str(last_human))

        # Check if triage is now complete
        # We need to re-run the gate with the updated answers context
        # The key insight: answers fill gaps, so we check what gaps remain
        remaining_gaps = _compute_remaining_gaps(updated_answers)

        if not remaining_gaps:
            # Triage complete - trigger re-classification
            await _trigger_reclassification(
                identity=identity,
                client=client,
                runner=runner,
                user_id=user_id,
                user_message=user_message,
                triage_answers=updated_answers,
            )
        else:
            # More questions needed - post next question
            provider = TriageProvider()
            next_question = provider.get_next_question(remaining_gaps, {})

            if next_question:
                blocks = build_triage_question_blocks(next_question, thread_ts)
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    blocks=blocks,
                    text=next_question.question_text,
                )
            else:
                # No more questions, but gaps remain - trigger anyway
                await _trigger_reclassification(
                    identity=identity,
                    client=client,
                    runner=runner,
                    user_id=user_id,
                    user_message=user_message,
                    triage_answers=updated_answers,
                )

    except json.JSONDecodeError as e:
        logger.error(f"Invalid triage button value JSON: {e}")
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Error processing your selection. Please try again.",
        )
    except Exception as e:
        logger.error(f"Triage answer handler error: {e}", exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Error processing answer: {e}",
        )


def _compute_remaining_gaps(answers) -> set:
    """Compute which gaps are still unaddressed by collected answers.

    Checks each gap type and returns those that don't have answers yet.

    Args:
        answers: TriageAnswers with collected values.

    Returns:
        Set of TriageGap values that still need addressing.
    """
    from src.schemas.triage import TriageGap

    remaining: set[TriageGap] = set()

    # UNKNOWN_MODE is addressed by mode_hint
    if not answers.mode_hint:
        remaining.add(TriageGap.UNKNOWN_MODE)

    # UNKNOWN_TARGET is addressed by target_hint or topic or jira_key
    if not answers.target_hint and not answers.topic and not answers.jira_key:
        remaining.add(TriageGap.UNKNOWN_TARGET)

    # UNKNOWN_SCOPE is addressed by scope_hint
    # Note: scope is only asked after mode is known to be "build"
    if answers.mode_hint == "build" and not answers.scope_hint:
        remaining.add(TriageGap.UNKNOWN_SCOPE)

    # MISSING_TOPIC is addressed by topic
    # Note: topic is only needed for "think" (review) mode
    if answers.mode_hint == "think" and not answers.topic:
        remaining.add(TriageGap.MISSING_TOPIC)

    # AMBIGUOUS_INTENT is addressed by clarification
    if not answers.clarification and not answers.mode_hint:
        remaining.add(TriageGap.AMBIGUOUS_INTENT)

    return remaining


async def _trigger_reclassification(
    identity,
    client: WebClient,
    runner,
    user_id: str,
    user_message: str,
    triage_answers,
) -> None:
    """Re-invoke the message handler with enriched triage context.

    This triggers a fresh run through the graph with triage_answers populated.
    The triage gate will see answers exist and pass through to classification.

    Args:
        identity: SessionIdentity for the thread.
        client: Slack WebClient.
        runner: GraphRunner instance.
        user_id: User ID who triggered the original request.
        user_message: Original user message to re-process.
        triage_answers: Collected TriageAnswers.
    """
    from src.slack.progress import ProgressTracker
    from src.slack.handlers.dispatch import _dispatch_result

    channel_id = identity.channel_id
    thread_ts = identity.thread_ts

    # Post acknowledgment
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="Thanks! Let me process your request now...",
    )

    tracker = ProgressTracker(client, channel_id, thread_ts)

    try:
        await tracker.start("Processing...")

        # Ensure triage_answers is in state before running
        state = await runner._get_current_state()
        state["triage_answers"] = triage_answers
        await runner._update_state({"triage_answers": triage_answers})

        # Re-run the graph with the message
        # The graph will see triage_answers in state and use them for classification
        result = await runner.run_with_message(
            message_text=user_message or "[Re-processing after triage]",
            user_id=user_id,
        )

        # Dispatch the result
        await _dispatch_result(result, identity, client, runner, tracker)

    except Exception as e:
        logger.error(f"Re-classification after triage failed: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Sorry, something went wrong while processing your request: {e}",
        )
    finally:
        await tracker.complete()
