"""Message and event handlers.

Ref: RESEARCH.md - Pattern 3: Event Handler
Ref: RESEARCH.md - Pitfall 4: Bot Responding to Itself
Ref: BOT_DESIGN.md - Two-Stage Intent Classification
"""

import logging
from slack_bolt.async_app import AsyncApp

from src.domain.entities import get_lifecycle
from src.intent import (
    classify_intent,
    RouterContext,
    PreGateResult,
    check_pregates,
)
from src.modes import dispatch_mode
from src.slack.client import SlackClient
from src.slack.dashboard import DashboardManager

logger = logging.getLogger(__name__)

# Cached bot user ID (resolved on first event)
_bot_user_id: str | None = None

# Track active process threads
_active_process_threads: set[str] = set()


async def _build_entity_summaries(channel_id: str) -> str:
    """Build entity summaries from event store for intent classification."""
    try:
        from src.infrastructure.aggregate_loader import load_aggregate

        aggregate = await load_aggregate(channel_id)
        if not aggregate.entities:
            return "No existing entities"

        summaries = []
        for eid, entity in list(aggregate.entities.items())[:20]:
            title = getattr(entity.content, "title", str(eid)[:8])
            state = get_lifecycle(entity).value
            etype = entity.entity_type.value
            summaries.append(f"- {title} ({etype}, {state}) [id: {eid}]")

        return "\n".join(summaries)
    except Exception as e:
        logger.debug(f"Could not load entity summaries: {e}")
        return "No existing entities"


async def _resolve_channel_name(client, channel_id: str) -> str:
    """Resolve channel name from Slack API."""
    try:
        info = await client.conversations_info(channel=channel_id)
        return info.get("channel", {}).get("name", channel_id)
    except Exception:
        return channel_id


def register_event_handlers(app: AsyncApp) -> None:
    """Register all event handlers on the Bolt app."""

    @app.event("message")
    async def handle_message(event: dict, say, client, logger) -> None:
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

        # Populate router context from projections
        channel_name = await _resolve_channel_name(client, channel_id)
        entity_summaries = await _build_entity_summaries(channel_id)

        context = RouterContext(
            channel_id=channel_id,
            channel_name=channel_name,
            thread_ts=thread_ts,
            thread_summary="",
            entity_summaries=entity_summaries,
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
    async def handle_app_mention(event: dict, say, client) -> None:
        """Handle @mentions of the bot.

        @mentions are treated like regular messages but always get a response.
        Fetches thread history for context when in a thread.
        """
        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts", event.get("ts"))
        message_bot_id = event.get("bot_id")

        logger.info(f"App mention in {channel_id} from {user_id}")

        # Fetch thread history for context
        thread_messages = []
        if thread_ts:
            try:
                replies = await client.conversations_replies(
                    channel=channel_id,
                    ts=thread_ts,
                    limit=50,
                )
                thread_messages = [
                    {"role": "assistant" if msg.get("bot_id") else "user",
                     "content": msg.get("text", "")}
                    for msg in replies.get("messages", [])
                ]
            except Exception as e:
                logger.warning(f"Failed to fetch thread history: {e}")

        # Build thread summary from messages for intent classification
        thread_summary = ""
        if thread_messages:
            thread_summary = "\n".join(
                f"{'Bot' if m['role'] == 'assistant' else 'User'}: {m['content'][:200]}"
                for m in thread_messages[-10:]  # Last 10 messages
            )

        # Populate entity summaries from event store
        channel_name = await _resolve_channel_name(client, channel_id)
        entity_summaries = await _build_entity_summaries(channel_id)

        # Build context
        context = RouterContext(
            channel_id=channel_id,
            channel_name=channel_name,
            thread_ts=thread_ts,
            thread_summary=thread_summary,
            entity_summaries=entity_summaries,
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

            # Dispatch to mode handler with thread context
            result = await dispatch_mode(
                message=text,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                intent=intent,
                thread_messages=thread_messages,
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

    @app.event("member_joined_channel")
    async def handle_member_joined(event: dict, client) -> None:
        """Handle bot being added to a channel - create dashboard.

        When the bot joins a channel, post and pin the status dashboard.
        Only triggers for the bot itself, not other users joining.
        """
        global _bot_user_id

        user_id = event.get("user", "")
        channel_id = event.get("channel", "")

        # Resolve our bot user ID if not cached
        if _bot_user_id is None:
            try:
                auth = await client.auth_test()
                _bot_user_id = auth.get("user_id", "")
            except Exception as e:
                logger.warning(f"Failed to resolve bot user ID: {e}")
                return

        # Only create dashboard when the bot itself joins
        if user_id != _bot_user_id:
            return

        logger.info(f"Bot added to channel {channel_id}, creating dashboard")

        try:
            slack_client = SlackClient(client)
            dashboard_mgr = DashboardManager(slack_client)
            await dashboard_mgr.create_or_update(channel_id=channel_id)
            logger.info(f"Dashboard created in {channel_id}")
        except Exception as e:
            logger.error(f"Failed to create dashboard in {channel_id}: {e}", exc_info=True)

    logger.info("Event handlers registered with intent routing")
