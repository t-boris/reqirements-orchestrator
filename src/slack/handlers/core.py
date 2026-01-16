"""Core Slack event handlers.

Handles app mentions, messages, and background async processing.
Contains the core event loop and message processing logic.
"""

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from slack_bolt import BoltContext
from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

if TYPE_CHECKING:
    from src.slack.progress import ProgressTracker

logger = logging.getLogger(__name__)

# Persistent background event loop for all async operations
# This ensures all async code (including the checkpointer) uses the same event loop
_background_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None


def _get_background_loop() -> asyncio.AbstractEventLoop:
    """Get or create the persistent background event loop."""
    global _background_loop, _loop_thread

    if _background_loop is None or not _background_loop.is_running():
        _background_loop = asyncio.new_event_loop()

        def run_loop():
            asyncio.set_event_loop(_background_loop)
            _background_loop.run_forever()

        _loop_thread = threading.Thread(target=run_loop, daemon=True, name="async_event_loop")
        _loop_thread.start()
        logger.info("Started persistent background event loop")

    return _background_loop


def _run_async(coro):
    """Run an async coroutine from a sync context.

    Submits the coroutine to the persistent background event loop.
    This ensures all async code uses the same event loop, which is required
    for the AsyncPostgresSaver checkpointer locks to work correctly.
    """
    loop = _get_background_loop()
    asyncio.run_coroutine_threadsafe(coro, loop)


def handle_app_mention(event: dict, say, client: WebClient, context: BoltContext):
    """Handle @mention events - start or continue conversation.

    Pattern: Ack fast, process async.
    """
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")  # Reply in thread
    user = event.get("user")
    text = event.get("text", "")

    logger.info(
        "App mention received",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "user": user,
            "text_preview": text[:100] if text else "",
        }
    )

    # Create session identity
    team_id = context.get("team_id", "")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Run async processing in background
    _run_async(_process_mention(identity, text, user, client, thread_ts, channel))


async def _build_conversation_context(
    client: WebClient,
    team_id: str,
    channel_id: str,
    thread_ts: str | None,
    message_ts: str,
) -> dict | None:
    """Build conversation context for injection into AgentState.

    Fetches conversation history from either:
    1. Stored summary + buffer (for listening-enabled channels)
    2. On-demand Slack API fetch (for other channels)

    Args:
        client: Slack WebClient for API calls
        team_id: Slack team/workspace ID
        channel_id: Channel ID where mention occurred
        thread_ts: Thread timestamp (if in a thread)
        message_ts: Current message timestamp

    Returns:
        ConversationContext as dict for AgentState, or None if no context available
    """
    from src.slack.history import (
        ConversationContext,
        fetch_channel_history,
        fetch_thread_history,
    )
    from src.db import get_connection, ListeningStore

    try:
        async with get_connection() as conn:
            store = ListeningStore(conn)
            listening_state = await store.get_state(team_id, channel_id)

            if listening_state and listening_state.enabled:
                # Use stored summary + buffer (listening-enabled channel)
                context = ConversationContext(
                    messages=listening_state.raw_buffer or [],
                    summary=listening_state.summary,
                    last_updated_at=listening_state.last_summary_at,
                )
                logger.debug(
                    "Using stored context",
                    extra={
                        "channel_id": channel_id,
                        "buffer_size": len(context.messages),
                        "has_summary": bool(context.summary),
                    }
                )
            else:
                # On-demand fetch (disabled channel)
                if thread_ts and thread_ts != message_ts:
                    # In a thread - fetch thread history
                    messages = fetch_thread_history(client, channel_id, thread_ts)
                else:
                    # Channel root - fetch recent channel messages
                    messages = fetch_channel_history(client, channel_id, before_ts=message_ts, limit=20)

                context = ConversationContext(messages=messages, summary=None)
                logger.debug(
                    "Fetched on-demand context",
                    extra={
                        "channel_id": channel_id,
                        "message_count": len(messages),
                    }
                )

        # Convert to dict for AgentState
        return {
            "messages": context.messages,
            "summary": context.summary,
            "last_updated_at": context.last_updated_at.isoformat() if context.last_updated_at else None,
        }

    except Exception as e:
        logger.warning(f"Failed to build conversation context: {e}")
        return None


async def _process_mention(
    identity: SessionIdentity,
    text: str,
    user: str,
    client: WebClient,
    thread_ts: str,
    channel: str,
):
    """Process app mention with event-first routing.

    Routing priority (from 20-CONTEXT.md):
    1. WorkflowEvent - handled before graph (event_router)
    2. PendingAction - handled before graph (event_router)
    3. Thread default intent - check and use
    4. Classified intent - route to flow
    """
    from src.slack.progress import ProgressTracker
    from src.slack.handlers.dispatch import _dispatch_result
    from src.slack.event_router import route_event, RouteResult
    from src.db import get_connection, EventStore

    # Create progress tracker for timing-based status feedback
    tracker = ProgressTracker(client, channel, thread_ts)

    try:
        await tracker.start("Processing...")

        runner = get_runner(identity)

        # Get current state for event routing
        state = await runner._get_current_state()

        # Event routing (for button clicks, slash commands)
        # For @mentions, this checks pending_action and thread_default
        async with get_connection() as conn:
            event_store = EventStore(conn)
            await event_store.ensure_table()

            routing = await route_event(
                body={"type": "message", "text": text},  # Simplified for mentions
                team_id=identity.team_id,
                state=state,
                event_store=event_store,
            )

        # Handle routing result
        if routing.result == RouteResult.DUPLICATE:
            logger.info("Duplicate event, skipping")
            await tracker.complete()
            return

        if routing.result == RouteResult.STALE_UI:
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=routing.error_message or "This action is no longer available.",
            )
            await tracker.complete()
            return

        if routing.result == RouteResult.CONTINUATION:
            # Handle pending action continuation
            await _handle_continuation(
                identity, routing.pending_action, state, text, user, client, thread_ts, channel, tracker
            )
            return

        # Default: run graph with intent classification (RouteResult.INTENT_CLASSIFY)
        # Build conversation context BEFORE running graph (Phase 11)
        conversation_context = await _build_conversation_context(
            client=client,
            team_id=identity.team_id,
            channel_id=channel,
            thread_ts=thread_ts,
            message_ts=thread_ts,  # Use thread_ts as the reference point
        )

        # Check for persona switch before running graph (Phase 9)
        await _check_persona_switch(runner, text, client, channel, thread_ts)

        result = await runner.run_with_message(text, user, conversation_context=conversation_context)

        # Use dispatcher for skill execution (dispatcher handles status updates)
        await _dispatch_result(result, identity, client, runner, tracker)

    except Exception as e:
        logger.error(f"Error processing mention: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Sorry, something went wrong. Please try again.",
        )
    finally:
        await tracker.complete()


async def _handle_continuation(
    identity: SessionIdentity,
    pending_action,
    state: dict,
    text: str,
    user: str,
    client: WebClient,
    thread_ts: str,
    channel: str,
    tracker,
):
    """Handle pending action continuation.

    Called when event_router returns RouteResult.CONTINUATION.
    Routes to appropriate continuation handler based on pending_action type.

    Args:
        identity: Session identity
        pending_action: The pending action type from event_router
        state: Current state dict
        text: The NEW message text from the user (not from state!)
        user: The user ID
        client: Slack WebClient
        thread_ts: Thread timestamp
        channel: Channel ID
        tracker: Progress tracker
    """
    from src.schemas.state import PendingAction

    logger.info(
        f"Handling continuation for pending_action={pending_action}",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "text_preview": text[:50] if text else "",
        },
    )

    # Get runner to continue processing
    runner = get_runner(identity)

    # Force REVIEW_CONTINUATION intent if we have review_context
    # This ensures the graph routes to review_continuation_flow
    review_context = state.get("review_context")
    if review_context:
        logger.info("Forcing REVIEW_CONTINUATION intent for active review")
        current_state = await runner._get_current_state()
        current_state["intent_result"] = {
            "intent": "REVIEW_CONTINUATION",
            "confidence": 1.0,
            "reasons": ["continuation: active review_context detected"],
        }
        await runner.graph.aupdate_state(runner._config, current_state)

    # Build conversation context
    conversation_context = await _build_conversation_context(
        client=client,
        team_id=identity.team_id,
        channel_id=channel,
        thread_ts=thread_ts,
        message_ts=thread_ts,
    )

    # Run graph with the NEW message (not the old one from state!)
    result = await runner.run_with_message(
        text,  # Use the new message from user
        user,  # Use the user ID passed in
        conversation_context=conversation_context,
    )

    # Dispatch result
    from src.slack.handlers.dispatch import _dispatch_result
    await _dispatch_result(result, identity, client, runner, tracker)


async def _check_persona_switch(
    runner,
    message_text: str,
    client: WebClient,
    channel: str,
    thread_ts: str,
) -> None:
    """Check for and apply persona switch based on message content.

    Notifies user when persona switches due to topic detection.
    """
    try:
        from src.personas.switcher import PersonaSwitcher
        from src.personas.types import PersonaName, PersonaReason

        state = await runner._get_current_state()
        current_persona = PersonaName(state.get("persona", "pm"))
        is_locked = state.get("persona_lock", False)

        switcher = PersonaSwitcher()
        switch_result = switcher.evaluate_switch(
            message=message_text,
            current_persona=current_persona,
            is_locked=is_locked,
        )

        if switch_result.switched:
            state_update = switcher.apply_switch(state, switch_result)
            # Update runner state
            new_state = {**state, **state_update}
            await runner._update_state(new_state)

            # Notify user of switch (only if detected, not explicit)
            if switch_result.reason == PersonaReason.DETECTED:
                from src.slack.blocks import build_persona_indicator
                indicator = build_persona_indicator(
                    switch_result.persona.value,
                    message_count=0,
                )
                if indicator:
                    client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=f"{indicator} {switch_result.message}",
                    )
    except Exception as e:
        # Non-blocking - log and continue
        logger.warning(f"Persona switch check failed: {e}")
