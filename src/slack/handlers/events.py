"""Message and event handlers.

Ref: RESEARCH.md - Pattern 3: Event Handler
Ref: RESEARCH.md - Pitfall 4: Bot Responding to Itself
Ref: BOT_DESIGN.md - Two-Stage Intent Classification
"""

import logging
from slack_bolt.async_app import AsyncApp

from src.intent import (
    classify_intent,
    RouterContext,
    PreGateResult,
    check_pregates,
)
from src.modes import dispatch_mode

logger = logging.getLogger(__name__)

# Track active process threads (will be populated by process orchestration in Phase 5)
_active_process_threads: set[str] = set()


def register_event_handlers(app: AsyncApp) -> None:
    """Register all event handlers on the Bolt app."""

    @app.event("message")
    async def handle_message(event: dict, say, logger) -> None:
        """Handle incoming messages with intent routing.

        Two-stage classification:
        1. PreGates catch commands, actions, approvals (deterministic)
        2. LLM Router classifies into SuperModes (CREATE, MODIFY, RECORD, CONVERSE)

        Ref: BOT_DESIGN.md - Two-Stage Intent Classification
        """
        # Extract event data
        message_bot_id = event.get("bot_id")
        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts")
        message_ts = event.get("ts")

        # Ignore message subtypes (edits, deletes, etc.)
        if event.get("subtype"):
            return

        # Quick check for bot messages before full routing
        if message_bot_id:
            logger.debug(f"Ignoring bot message from {message_bot_id}")
            return

        # Skip @mentions - they're handled by handle_app_mention to avoid duplicates
        if "<@" in text:
            logger.debug("Skipping @mention in message handler (handled by app_mention)")
            return

        logger.info(f"Message in {channel_id} from {user_id}: {text[:50]}...")

        # Build router context
        # Note: In Phase 4+, we'll populate these from entity projections
        context = RouterContext(
            channel_id=channel_id,
            channel_name=channel_id,  # Will be resolved in later phases
            thread_ts=thread_ts,
            thread_summary="",  # Will be populated in later phases
            entity_summaries="",  # Will be populated in later phases
            active_process_threads=_active_process_threads,
        )

        try:
            # Classify intent (PreGates + LLM Router)
            intent = await classify_intent(
                message=text,
                event_type="message",
                context=context,
                message_bot_id=message_bot_id,
            )

            logger.info(
                f"Intent classified: mode={intent.mode}, "
                f"confidence={intent.confidence:.2f}"
            )

            # Dispatch to mode handler
            result = await dispatch_mode(
                message=text,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                intent=intent,
            )

            # Send response
            if result.response_text:
                # Determine response location
                response_thread = thread_ts or message_ts

                if result.response_blocks:
                    await say(
                        text=result.response_text,
                        blocks=result.response_blocks,
                        thread_ts=response_thread,
                    )
                else:
                    await say(
                        text=result.response_text,
                        thread_ts=response_thread,
                    )

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            # Don't expose internal errors to users
            await say(
                text="Sorry, I encountered an error processing your message. Please try again.",
                thread_ts=thread_ts or message_ts,
            )

    @app.event("app_mention")
    async def handle_app_mention(event: dict, say) -> None:
        """Handle @mentions of the bot.

        @mentions are treated like regular messages but always get a response.
        """
        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts", event.get("ts"))
        message_bot_id = event.get("bot_id")

        logger.info(f"App mention in {channel_id} from {user_id}")

        # Build context
        context = RouterContext(
            channel_id=channel_id,
            channel_name=channel_id,
            thread_ts=thread_ts,
            thread_summary="",
            entity_summaries="",
            active_process_threads=_active_process_threads,
        )

        try:
            # Classify intent
            intent = await classify_intent(
                message=text,
                event_type="app_mention",
                context=context,
                message_bot_id=message_bot_id,
            )

            # Dispatch to mode handler
            result = await dispatch_mode(
                message=text,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                intent=intent,
            )

            # Send response
            if result.response_text:
                if result.response_blocks:
                    await say(
                        text=result.response_text,
                        blocks=result.response_blocks,
                        thread_ts=thread_ts,
                    )
                else:
                    await say(
                        text=result.response_text,
                        thread_ts=thread_ts,
                    )

        except Exception as e:
            logger.error(f"Error processing mention: {e}", exc_info=True)
            await say(
                text="Sorry, I encountered an error. Please try again.",
                thread_ts=thread_ts,
            )

    logger.info("Event handlers registered with intent routing")
