"""Core Slack event handlers.

Handles app mentions, messages, and background async processing.
Contains the core event loop and message processing logic.
"""

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Optional

from slack_bolt import BoltContext
from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner
from src.debug.collector import DebugCollector

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

    Exceptions in the coroutine are logged but not re-raised (fire-and-forget).
    """
    loop = _get_background_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)

    # Add callback to log any exceptions (prevents silent swallowing)
    def handle_exception(fut):
        try:
            # This will raise if coroutine raised an exception
            fut.result()
        except Exception:
            logger.exception("Exception in background coroutine")

    future.add_done_callback(handle_exception)


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


async def _capture_user_metadata(
    client: WebClient,
    user_id: str,
    team_id: str,
) -> None:
    """Capture and cache user metadata from Slack.

    Fetches user info from Slack API and stores/updates in database.
    Non-blocking - logs errors but doesn't fail the request.

    Args:
        client: Slack WebClient for API calls
        user_id: Slack user ID to capture
        team_id: Slack workspace ID
    """
    from src.db import get_connection
    from src.db.user_metadata_store import UserMetadataStore

    try:
        # Fetch user info from Slack
        result = client.users_info(user=user_id)
        if not result.get("ok"):
            logger.debug(f"users_info returned not ok for {user_id}")
            return

        user_data = result.get("user", {})
        profile = user_data.get("profile", {})

        async with get_connection() as conn:
            store = UserMetadataStore(conn)
            await store.ensure_table()
            await store.upsert(
                slack_user_id=user_id,
                team_id=team_id,
                display_name=profile.get("display_name") or user_data.get("name", "Unknown"),
                real_name=profile.get("real_name"),
                email=profile.get("email"),
                avatar_url=profile.get("image_72"),
            )
        logger.debug(f"Captured user metadata for {user_id}")
    except Exception as e:
        # Non-blocking - log and continue
        logger.debug(f"Could not capture user metadata: {e}")


async def _record_participation(
    channel_id: str,
    thread_ts: str,
    user_id: str,
) -> None:
    """Record user participation in thread.

    Tracks who participates in each thread for:
    - Mention rules (direct question → mention that user)
    - Turn-taking awareness
    - Multi-user coordination

    Non-blocking - logs errors but doesn't fail the request.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        user_id: Slack user ID

    Phase 27.2 - Participant Map & Turn-Taking
    """
    from src.db import get_connection
    from src.db.participant_store import ThreadParticipantStore

    try:
        async with get_connection() as conn:
            store = ThreadParticipantStore(conn)
            await store.ensure_table()
            await store.record_message(channel_id, thread_ts, user_id)
        logger.debug(f"Recorded participation for {user_id} in {channel_id}/{thread_ts}")
    except Exception as e:
        # Non-blocking - log and continue
        logger.debug(f"Could not record participation: {e}")


def _is_processing_request(state: dict) -> bool:
    """Check if state indicates active processing.

    Only blocks if we're in middle of multi-step flow.

    Args:
        state: Current agent state dict

    Returns:
        True if thread is busy with a blocking pending_action

    Phase 27.2 - Participant Map & Turn-Taking
    """
    from src.schemas.state import PendingAction

    pending = state.get("pending_action")
    if not pending:
        return False

    # Only block for these multi-step flows where interleaving would cause issues
    blocking_actions = {
        PendingAction.WAITING_APPROVAL,
        PendingAction.WAITING_SCOPE_CHOICE,
        PendingAction.WAITING_UPDATE_CONFIRM,
        PendingAction.WAITING_STORY_EDIT,
        PendingAction.WAITING_DECISION_EDIT,
    }

    # Handle both enum and string values
    if isinstance(pending, str):
        return pending in {a.value for a in blocking_actions}
    return pending in blocking_actions


async def _queue_request(
    runner,
    user_id: str,
    message_text: str,
    message_ts: str,
) -> None:
    """Add request to queue for later processing.

    Called when a thread is busy processing another request.
    Queued requests will be processed after the current operation completes.

    Args:
        runner: Graph runner instance
        user_id: User ID who made the request
        message_text: The message text
        message_ts: Slack message timestamp

    Phase 27.2 - Participant Map & Turn-Taking
    """
    from datetime import datetime, timezone

    state = await runner._get_current_state()
    queued = state.get("queued_requests", [])
    queued.append({
        "user_id": user_id,
        "message_text": message_text,
        "message_ts": message_ts,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    })
    await runner._update_state({"queued_requests": queued})


async def _build_context_packet(
    channel_id: str,
    thread_ts: str,
    mode: Optional[str] = None,
) -> Optional[dict]:
    """Build context packet for graph execution.

    Uses ContextBuilder to assemble structured context with:
    - Layer A: Canonical state from DB (decisions, reviews)
    - Layer B: Working history with rendered blocks
    - Layer C: Retrieval add-ons (attachments, Jira)

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        mode: Optional SuperMode value (defaults to CHAT)

    Returns:
        Serialized packet dict or None on error.

    Phase 38-06: Context Architecture integration.
    """
    try:
        from src.context import ContextSpec, ContextBuilder
        from src.schemas.intent import SuperMode

        # Determine mode - default to CHAT if not specified
        super_mode = SuperMode.CHAT
        if mode:
            try:
                super_mode = SuperMode(mode.lower())
            except ValueError:
                pass

        spec = ContextSpec(
            mode=super_mode,
            target=f"{channel_id}:{thread_ts}",
            purpose="process user message",
            budget_tokens=4000,
        )
        builder = ContextBuilder()
        packet = await builder.build(spec)
        return packet.model_dump()
    except Exception as e:
        logger.debug(f"Could not build context packet: {e}")
        return None


async def _resolve_thread_context(
    channel_id: str,
    thread_ts: str,
    collector: Optional[DebugCollector] = None,
):
    """Resolve thread context for anchor-based object binding.

    Implements Rule A3 (Context Inheritance) from Phase 33 - Anchor Message Architecture.
    When a message arrives in a thread, determine what object the thread is managing.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp (parent message ts)
        collector: Optional debug collector for debug mode

    Returns:
        ThreadContext if thread is anchored to an object, None otherwise.

    Phase 33 - Anchor Message Architecture
    """
    from src.slack.context_resolver import resolve_thread_context

    try:
        thread_context = await resolve_thread_context(
            channel_id,
            thread_ts,
            hydrate=True,  # Load full entity for downstream use
        )

        if thread_context and collector:
            collector.add_entry("decision", "Thread Context Resolved", {
                "anchor_type": thread_context.anchor_type.value,
                "object_id": thread_context.object_id,
                "display_id": thread_context.display_id,
                "has_entity": thread_context.has_entity,
            })
        elif collector:
            collector.add_entry("decision", "Thread Context Resolved", {
                "result": "no_anchor",
            })

        return thread_context

    except Exception as e:
        logger.debug(f"Could not resolve thread context: {e}")
        if collector:
            collector.add_entry("decision", "Thread Context Error", {
                "error": str(e),
            })
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

    # Check debug mode at start (before processing)
    debug_enabled = await _is_debug_enabled(channel)
    collector: Optional[DebugCollector] = DebugCollector() if debug_enabled else None

    # Capture user metadata for multi-user support (Phase 27.1)
    await _capture_user_metadata(client, user, identity.team_id)

    # Record participation for multi-user tracking (Phase 27.2)
    await _record_participation(channel, thread_ts, user)

    # Ensure channel context exists (lazy creation for existing channels)
    try:
        from src.db import get_connection
        from src.db.channel_context_store import ChannelContextStore

        async with get_connection() as conn:
            ctx_store = ChannelContextStore(conn)
            await ctx_store.get_or_create(identity.team_id, channel)
    except Exception as e:
        logger.debug(f"Could not ensure channel context: {e}")

    try:
        await tracker.start("Processing...")

        runner = get_runner(identity)

        # Get current state for event routing
        state = await runner._get_current_state()

        # Check if thread is busy processing another request (Phase 27.2)
        if _is_processing_request(state):
            # Queue this request for later processing
            await _queue_request(runner, user, text, thread_ts)
            if collector:
                collector.add_entry("decision", "Request Queued", {
                    "reason": "thread_busy",
                    "pending_action": str(state.get("pending_action")),
                })
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"<@{user}>, I'm currently processing another request. Yours is queued and I'll get to it shortly.",
            )
            await tracker.complete()
            return

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
            if collector:
                collector.add_entry("decision", "Event Routing", {
                    "result": "DUPLICATE",
                    "action": "skipped",
                })
            await tracker.complete()
            return

        if routing.result == RouteResult.STALE_UI:
            if collector:
                collector.add_entry("decision", "Event Routing", {
                    "result": "STALE_UI",
                    "action": "error_message",
                })
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=routing.error_message or "This action is no longer available.",
            )
            await tracker.complete()
            return

        if routing.result == RouteResult.CONTINUATION:
            if collector:
                collector.add_entry("decision", "Event Routing", {
                    "result": "CONTINUATION",
                    "pending_action": str(routing.pending_action),
                })
            # Handle pending action continuation
            await _handle_continuation(
                identity, routing.pending_action, state, text, user, client, thread_ts, channel, tracker, collector
            )
            return

        # Log intent classification start
        if collector:
            collector.add_entry("intent", "Event Routing", {
                "result": "INTENT_CLASSIFY",
                "message_preview": text[:100],
            })

        # Default: run graph with intent classification (RouteResult.INTENT_CLASSIFY)
        # Build conversation context BEFORE running graph (Phase 11)
        conversation_context = await _build_conversation_context(
            client=client,
            team_id=identity.team_id,
            channel_id=channel,
            thread_ts=thread_ts,
            message_ts=thread_ts,  # Use thread_ts as the reference point
        )

        # Resolve thread context (Phase 33 - Anchor Message Architecture)
        # This implements Rule A3: Context Inheritance
        thread_context = await _resolve_thread_context(channel, thread_ts, collector)

        # Build context packet (Phase 38-06 - Context Architecture)
        # Opt-in: builds structured context packet for future graph nodes
        context_packet = await _build_context_packet(channel, thread_ts)
        if context_packet and collector:
            collector.add_entry("context", "Context Packet Built", {
                "total_tokens": context_packet.get("total_tokens", 0),
                "has_canonical": bool(context_packet.get("canonical")),
                "has_history": bool(context_packet.get("history")),
                "has_retrieved": bool(context_packet.get("retrieved")),
            })

        # Check for persona switch before running graph (Phase 9)
        await _check_persona_switch(runner, text, client, channel, thread_ts)

        result = await runner.run_with_message(
            text,
            user,
            conversation_context=conversation_context,
            thread_context=thread_context,
        )

        # Log decision from graph result
        if collector:
            collector.add_entry("decision", "Graph Decision", {
                "action": result.get("action", "unknown"),
                "intent": result.get("intent_result", {}).get("intent", "unknown") if result.get("intent_result") else "unknown",
            })

        # Use dispatcher for skill execution (dispatcher handles status updates)
        await _dispatch_result(result, identity, client, runner, tracker)

    except Exception as e:
        logger.error(f"Error processing mention: {e}", exc_info=True)
        if collector:
            collector.add_error(e, "process_mention")
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Sorry, something went wrong. Please try again.",
        )
    finally:
        await tracker.complete()
        # Post debug output if enabled
        if collector and collector.entries:
            try:
                await _post_debug_output(client, channel, thread_ts, collector)
            except Exception as debug_err:
                logger.warning(f"Failed to post debug output: {debug_err}")


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
    collector: Optional[DebugCollector] = None,
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
        collector: Optional debug collector for debug mode
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

    if collector:
        collector.add_entry("intent", "Continuation Handler", {
            "pending_action": str(pending_action),
            "message_preview": text[:100] if text else "",
        })

    # Get runner to continue processing
    runner = get_runner(identity)

    # Special handling for WAITING_UPDATE_CONFIRM - conversational update refinement
    if pending_action == PendingAction.WAITING_UPDATE_CONFIRM:
        from src.slack.handlers.update import refine_update_from_feedback

        if collector:
            collector.add_entry("decision", "Update Refinement", {
                "action": "refine_update_from_feedback",
            })
        processed = await refine_update_from_feedback(identity, client, text)
        if processed:
            if collector:
                collector.add_entry("decision", "Update Refinement Result", {
                    "processed": True,
                })
            await tracker.complete()
            # Post debug output for continuation path
            if collector and collector.entries:
                try:
                    await _post_debug_output(client, channel, thread_ts, collector)
                except Exception as debug_err:
                    logger.warning(f"Failed to post debug output: {debug_err}")
            return
        # If not processed (no pending_update), fall through to normal flow

    # Force REVIEW_CONTINUATION intent if we have review_context
    # This ensures the graph routes to review_continuation_flow
    review_context = state.get("review_context")
    if review_context:
        logger.info("Forcing REVIEW_CONTINUATION intent for active review")
        if collector:
            collector.add_entry("intent", "Review Continuation Forced", {
                "has_review_context": True,
            })
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

    # Resolve thread context (Phase 33 - Anchor Message Architecture)
    thread_context = await _resolve_thread_context(channel, thread_ts, collector)

    # Run graph with the NEW message (not the old one from state!)
    result = await runner.run_with_message(
        text,  # Use the new message from user
        user,  # Use the user ID passed in
        conversation_context=conversation_context,
        thread_context=thread_context,
    )

    # Log decision from graph result
    if collector:
        collector.add_entry("decision", "Continuation Graph Decision", {
            "action": result.get("action", "unknown"),
            "intent": result.get("intent_result", {}).get("intent", "unknown") if result.get("intent_result") else "unknown",
        })

    # Dispatch result
    from src.slack.handlers.dispatch import _dispatch_result
    await _dispatch_result(result, identity, client, runner, tracker)

    # Post debug output for continuation path
    if collector and collector.entries:
        try:
            await _post_debug_output(client, channel, thread_ts, collector)
        except Exception as debug_err:
            logger.warning(f"Failed to post debug output: {debug_err}")


async def _is_debug_enabled(channel_id: str) -> bool:
    """Check if debug mode is enabled for channel."""
    from src.db import get_connection
    from src.db.debug_store import DebugStore

    try:
        async with get_connection() as conn:
            store = DebugStore(conn)
            return await store.is_enabled(channel_id)
    except Exception:
        return False


async def _post_debug_output(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    collector: DebugCollector,
) -> None:
    """Post debug output as thread reply.

    Truncates LLM prompts to 300 chars in message.
    Uploads full content as .txt file if needed.
    """
    from src.slack.blocks.debug import build_debug_output_blocks

    blocks, full_content = build_debug_output_blocks(collector)

    # Post debug message
    result = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        blocks=blocks,
        text="Debug output",
    )

    # Upload full content as file if needed
    if full_content:
        client.files_upload_v2(
            channel=channel_id,
            thread_ts=thread_ts,
            content=full_content,
            filename=f"debug_{thread_ts}.txt",
            title="Full Debug Output",
        )


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
