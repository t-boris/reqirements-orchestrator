"""Message and event handlers.

Ref: RESEARCH.md - Pattern 3: Event Handler
Ref: RESEARCH.md - Pitfall 4: Bot Responding to Itself
"""
import logging
from slack_bolt.async_app import AsyncApp

logger = logging.getLogger(__name__)


def register_event_handlers(app: AsyncApp) -> None:
    """Register all event handlers on the Bolt app."""

    @app.event("message")
    async def handle_message(event: dict, say, logger) -> None:
        """Handle incoming messages.

        CRITICAL: Check for bot_id to avoid infinite loops.
        Phase 3 will add intent routing here.
        """
        # Avoid responding to bot messages (including ourselves)
        if event.get("bot_id"):
            return

        # Ignore message subtypes (edits, deletes, etc.)
        if event.get("subtype"):
            return

        channel_id = event.get("channel")
        user_id = event.get("user")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts")
        message_ts = event.get("ts")

        logger.info(f"Message in {channel_id} from {user_id}: {text[:50]}...")

        # For now, just log. Phase 3 adds intent routing.
        # The actual response logic will be added in Phase 3.
        # This handler establishes the plumbing.

    @app.event("app_mention")
    async def handle_app_mention(event: dict, say) -> None:
        """Handle @mentions of the bot.

        When someone @mentions the bot, we respond.
        Phase 3 will add intent routing here.
        """
        user_id = event.get("user")
        thread_ts = event.get("thread_ts", event.get("ts"))

        # Acknowledge the mention - actual routing comes in Phase 3
        await say(
            text=f"Hi <@{user_id}>! I received your message. Intent routing coming in Phase 3.",
            thread_ts=thread_ts,
        )

    logger.info("Event handlers registered")
