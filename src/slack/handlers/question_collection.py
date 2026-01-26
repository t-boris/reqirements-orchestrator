"""Button handlers for question collection answers.

Handles button clicks when user answers LLM's clarifying questions
during the question collection phase.
"""
import json
import logging
import re

from slack_bolt import Ack, App
from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def register_question_collection_handlers(app: App) -> None:
    """Register question collection button handlers.

    Registers handlers for collect_answer_* button clicks.
    """

    @app.action(re.compile(r"^collect_answer_.*"))
    def handle_collect_answer_button(ack: Ack, body: dict, client: WebClient, action: dict):
        """Handle collection question button click (sync wrapper)."""
        ack()

        channel_id = body.get("channel", {}).get("id", "")
        message_ts = body.get("message", {}).get("ts")
        thread_ts = body.get("message", {}).get("thread_ts") or message_ts
        user_id = body.get("user", {}).get("id", "")
        value = action.get("value", "")

        _run_async(
            handle_collect_answer(
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

    logger.info("Registered question collection button handlers")


async def handle_collect_answer(
    body: dict,
    client: WebClient,
    action_id: str,
    value: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    message_ts: str | None = None,
) -> None:
    """Handle collection question button click.

    Flow:
    1. Parse button value
    2. Update original message to show selection
    3. Store answer in state
    4. Re-run question_collection to check for more questions
    5. If no more questions → proceed to actual flow

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
    from src.slack.session import SessionIdentity
    from src.graph.runner import get_runner
    from src.slack.progress import ProgressTracker

    try:
        # Parse button value
        button_data = json.loads(value)
        question_text = button_data.get("question_text", "")
        answer_value = button_data.get("value", "")
        answer_label = button_data.get("label", answer_value)

        logger.info(
            "Collection answer received",
            extra={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "question": question_text[:50],
                "answer": answer_label,
            },
        )

        # Update the original message to show selection
        if message_ts:
            try:
                # Get original question text from message
                original_blocks = body.get("message", {}).get("blocks", [])
                orig_question = question_text
                for block in original_blocks:
                    if block.get("type") == "section":
                        text = block.get("text", {}).get("text", "")
                        if text.startswith("*") and text.endswith("*"):
                            orig_question = text
                            break

                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text=f"{orig_question} → {answer_label}",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": orig_question,
                            },
                        },
                        {
                            "type": "context",
                            "elements": [{
                                "type": "mrkdwn",
                                "text": f"✓ *{answer_label}*",
                            }],
                        },
                    ],
                )
            except Exception as e:
                logger.warning(f"Could not update collection question message: {e}")

        # Get runner and update state
        identity = SessionIdentity(
            team_id="",
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        runner = get_runner(identity)
        state = await runner._get_current_state()

        # Store the answer
        collected_answers = state.get("collected_answers", {})
        collected_answers[question_text[:100]] = answer_label
        await runner._update_state({
            "collected_answers": collected_answers,
            "question_collection_pending": False,
        })

        # Re-run the graph to check for more questions
        tracker = ProgressTracker(client, channel_id, thread_ts)

        try:
            await tracker.start("Processing...")

            # Get original user message
            user_message = state.get("user_message", "")

            # Re-run - question_collection will check if more questions needed
            result = await runner.run_with_message(
                message_text=user_message or "[Processing after answer]",
                user_id=user_id,
            )

            # Dispatch the result (either more questions or actual flow)
            from src.slack.handlers.dispatch import _dispatch_result
            await _dispatch_result(result, identity, client, runner, tracker)

        except Exception as e:
            logger.error(f"Failed to continue after collection answer: {e}", exc_info=True)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"Sorry, something went wrong: {e}",
            )
        finally:
            await tracker.complete()

    except json.JSONDecodeError as e:
        logger.error(f"Invalid collection button value JSON: {e}")
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Error processing your selection. Please try again.",
        )
    except Exception as e:
        logger.error(f"Collection answer handler error: {e}", exc_info=True)
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Error processing answer: {e}",
        )
