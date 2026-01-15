"""Slack event handlers with fast-ack pattern."""

import asyncio
import logging
import threading
from slack_bolt import Ack, BoltContext
from slack_bolt.kwargs_injection.args import Args
from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

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
    """Async processing for @mention - runs graph and dispatches to skills."""
    try:
        runner = get_runner(identity)

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

        # Use dispatcher for skill execution
        await _dispatch_result(result, identity, client, runner)

    except Exception as e:
        logger.error(f"Error processing mention: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Sorry, something went wrong. Please try again.",
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


async def _dispatch_result(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
    runner,
):
    """Dispatch graph result to appropriate skill via dispatcher.

    Clean separation:
    - Runner: manages graph execution, returns DecisionResult
    - Dispatcher: calls appropriate skill based on decision
    - Handler: orchestrates and handles Slack-specific response
    """
    from src.skills.dispatcher import SkillDispatcher
    from src.graph.nodes.decision import DecisionResult

    action = result.get("action", "continue")

    if action == "intro" or action == "nudge":
        # Empty draft - send intro or nudge message
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=result.get("message", "Tell me what you'd like to work on."),
        )

    elif action == "ask":
        # Build DecisionResult from runner result
        decision = DecisionResult(
            action="ask",
            questions=result.get("questions", []),
            reason=result.get("reason", ""),
            is_reask=result.get("pending_questions", {}).get("re_ask_count", 0) > 0 if result.get("pending_questions") else False,
            reask_count=result.get("pending_questions", {}).get("re_ask_count", 0) if result.get("pending_questions") else 0,
        )

        dispatcher = SkillDispatcher(client, identity)
        skill_result = await dispatcher.dispatch(decision, result.get("draft"))

        # Store pending questions in runner state
        if skill_result.get("success") and skill_result.get("pending_questions"):
            await runner.store_pending_questions(skill_result["pending_questions"])

    elif action == "preview":
        draft = result.get("draft")
        if draft:
            decision = DecisionResult(
                action="preview",
                reason=result.get("reason", ""),
            )

            dispatcher = SkillDispatcher(client, identity)
            await dispatcher.dispatch(decision, draft)

    elif action == "ready":
        # Approved - notify user
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="Ticket approved and ready to create in Jira!",
        )

    elif action == "error":
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Sorry, I encountered an error: {result.get('error', 'Unknown error')}",
        )

    else:
        # Continue - acknowledge receipt
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="Got it! I'm collecting the requirements.",
        )


async def _update_listening_context(
    team_id: str,
    channel_id: str,
    message: dict,
) -> None:
    """Update rolling summary for listening-enabled channel.

    Maintains the two-layer context pattern:
    - Adds new message to raw buffer
    - When buffer exceeds 30, compresses older messages into summary

    This runs for EVERY message in enabled channels, so kept lightweight.
    Summary updates only happen when buffer threshold is exceeded.

    Args:
        team_id: Slack team/workspace ID
        channel_id: Channel ID
        message: Slack message dict to add to buffer
    """
    from src.db import get_connection, ListeningStore
    from src.slack.summarizer import update_rolling_summary, should_update_summary
    from src.llm import get_llm

    try:
        async with get_connection() as conn:
            store = ListeningStore(conn)

            # Quick check if listening enabled (lightweight)
            if not await store.is_enabled(team_id, channel_id):
                return  # Not listening, skip

            # Get current state
            summary, raw_buffer = await store.get_summary(team_id, channel_id)

            # Add new message to buffer
            raw_buffer = raw_buffer or []
            raw_buffer.append({
                "user": message.get("user", "unknown"),
                "text": message.get("text", ""),
                "ts": message.get("ts", ""),
            })

            # Check if summary update needed (buffer > 30)
            if should_update_summary(len(raw_buffer), threshold=30):
                # Take messages to summarize (keep last 20 raw)
                to_summarize = raw_buffer[:-20]
                raw_buffer = raw_buffer[-20:]

                # Update summary with older messages
                llm = get_llm()
                summary = await update_rolling_summary(llm, summary, to_summarize)

                logger.debug(
                    "Updated rolling summary",
                    extra={
                        "channel_id": channel_id,
                        "messages_summarized": len(to_summarize),
                        "buffer_size": len(raw_buffer),
                    }
                )

            # Store updated state
            await store.update_summary(team_id, channel_id, summary, raw_buffer)

    except Exception as e:
        # Non-blocking - log and continue
        logger.warning(f"Failed to update listening context: {e}")


def handle_message(event: dict, say, client: WebClient, context: BoltContext):
    """Handle message events for listening and thread participation.

    Two responsibilities:
    1. Update rolling context for listening-enabled channels (all messages)
    2. Process thread messages where bot is already participating

    Skips:
    - Bot messages
    - Message edits/deletes
    """
    # Skip bot messages
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    # Skip message edits/deletes
    subtype = event.get("subtype")
    if subtype in ("message_changed", "message_deleted"):
        return

    channel = event.get("channel")
    team_id = context.get("team_id", "")

    # Update listening context for ALL messages in enabled channels (Phase 11)
    # This runs async in background to not block message processing
    _run_async(_update_listening_context(team_id, channel, event))

    # Thread message processing (existing behavior)
    # Only processes messages in threads where bot has an active session
    if "thread_ts" not in event:
        return  # Not a thread message, nothing more to do

    thread_ts = event["thread_ts"]
    user = event.get("user")
    text = event.get("text", "")

    logger.info(
        "Thread message received",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "user": user,
        }
    )

    # Create session identity
    team_id = context.get("team_id", "")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Check if we have an active session for this thread
    from src.graph.runner import _runners
    if identity.session_id in _runners:
        # Active session - process message
        _run_async(_process_thread_message(identity, text, user, client, thread_ts, channel))


async def _process_thread_message(
    identity: SessionIdentity,
    text: str,
    user: str,
    client: WebClient,
    thread_ts: str,
    channel: str,
):
    """Async processing for thread message - continues graph and dispatches to skills."""
    try:
        runner = get_runner(identity)

        # Build conversation context BEFORE running graph (Phase 11)
        conversation_context = await _build_conversation_context(
            client=client,
            team_id=identity.team_id,
            channel_id=channel,
            thread_ts=thread_ts,
            message_ts=thread_ts,
        )

        # Check for persona switch before running graph (Phase 9)
        await _check_persona_switch(runner, text, client, channel, thread_ts)

        result = await runner.run_with_message(text, user, conversation_context=conversation_context)

        # Use dispatcher for skill execution (same as _process_mention)
        await _dispatch_result(result, identity, client, runner)

    except Exception as e:
        logger.error(f"Error processing thread message: {e}", exc_info=True)


def handle_help_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /help slash command - show all available commands."""
    ack()

    channel = command.get("channel_id")

    help_text = """*MARO - Requirements Assistant*

I help turn ideas, bugs, and features into Jira tickets.

*How to use:*
• @mention me with your idea, and I'll help structure it into a ticket
• Answer my questions to fill in the details
• Review and approve the draft before I create it in Jira

*Commands:*
• `/help` - Show this help message
• `/jira create [type]` - Start a new ticket
• `/jira search <query>` - Search existing tickets
• `/jira status` - Show current session status
• `/persona pm|security|architect` - Switch persona
• `/persona lock` - Lock persona for this thread
• `/persona status` - Show current persona

*Tips:*
• Be specific about the problem you're solving
• Include acceptance criteria when you can
• I'll ask clarifying questions if needed"""

    say(text=help_text, channel=channel)


def handle_jira_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /jira slash command with subcommands.

    Subcommands:
    - /jira create [type] - Start new ticket session
    - /jira search <query> - Search existing tickets
    - /jira status - Show current session status
    """
    ack()  # Ack immediately

    channel = command.get("channel_id")
    user = command.get("user_id")
    text = command.get("text", "").strip()

    # Parse subcommand
    parts = text.split(maxsplit=1)
    subcommand = parts[0].lower() if parts else "help"
    args = parts[1] if len(parts) > 1 else ""

    logger.info(
        "Jira command received",
        extra={
            "channel": channel,
            "user": user,
            "subcommand": subcommand,
            "args": args,
        }
    )

    if subcommand == "create":
        ticket_type = args.capitalize() if args else None
        say(
            text=f"Starting new ticket session{' for ' + ticket_type if ticket_type else ''}...",
            channel=channel,
        )
        # TODO: Route to session creation in 04-04

    elif subcommand == "search":
        if not args:
            say(text="Usage: /jira search <query>", channel=channel)
            return
        say(text=f"Searching for: {args}...", channel=channel)
        # TODO: Implement Jira search in Phase 7

    elif subcommand == "status":
        say(text="No active session in this channel.", channel=channel)
        # TODO: Query session status in 04-04

    else:
        say(
            text="Available commands:\n• `/jira create [type]` - Start new ticket\n• `/jira search <query>` - Search tickets\n• `/jira status` - Session status",
            channel=channel,
        )


def handle_persona_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /persona slash command (sync wrapper).

    Delegates to async implementation via _run_async().
    """
    ack()  # Ack immediately
    _run_async(_handle_persona_command_async(command, say, client))


async def _handle_persona_command_async(command: dict, say, client: WebClient):
    """Async implementation of /persona slash command.

    Commands:
    - /persona [name] - Switch to persona (pm, security, architect)
    - /persona lock - Lock current persona for thread
    - /persona unlock - Allow persona switching again
    - /persona status - Show current persona and validators
    - /persona list - Show available personas
    """
    channel = command.get("channel_id")
    thread_ts = command.get("thread_ts") or command.get("ts", "")
    user = command.get("user_id")
    text = command.get("text", "").strip()

    logger.info(
        "Persona command received",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "user": user,
            "command_text": text,
        }
    )

    # Get session state if we have a thread
    from src.personas.commands import handle_persona_command as exec_persona_cmd

    # Build minimal state if no session exists
    state = {
        "persona": "pm",
        "persona_lock": False,
        "persona_reason": "default",
    }

    # Try to get actual session state
    if thread_ts:
        try:
            identity = SessionIdentity(
                team_id=command.get("team_id", "default"),
                channel_id=channel,
                thread_ts=thread_ts,
            )
            # Check if runner exists for this session
            from src.graph.runner import _runners
            if identity.session_id in _runners:
                runner = get_runner(identity)
                current_state = await runner._get_current_state()
                state = {
                    "persona": current_state.get("persona", "pm"),
                    "persona_lock": current_state.get("persona_lock", False),
                    "persona_reason": current_state.get("persona_reason", "default"),
                    "persona_confidence": current_state.get("persona_confidence"),
                }
        except Exception as e:
            logger.warning(f"Could not get session state: {e}")

    # Execute command
    result = exec_persona_cmd(text, state)

    # Send response
    response_kwargs = {
        "channel": channel,
        "text": result.message,
    }
    if thread_ts:
        response_kwargs["thread_ts"] = thread_ts

    client.chat_postMessage(**response_kwargs)

    # Update session if state changed and we have a runner
    if result.state_update and thread_ts:
        try:
            identity = SessionIdentity(
                team_id=command.get("team_id", "default"),
                channel_id=channel,
                thread_ts=thread_ts,
            )
            from src.graph.runner import _runners
            if identity.session_id in _runners:
                runner = get_runner(identity)
                current_state = await runner._get_current_state()
                new_state = {**current_state, **result.state_update}
                await runner._update_state(new_state)
                logger.info(
                    "Persona state updated",
                    extra={
                        "session_id": identity.session_id,
                        "state_update": result.state_update,
                    }
                )
        except Exception as e:
            logger.warning(f"Could not update session state: {e}")


async def handle_epic_selection(ack, body, client: WebClient, action):
    """Handle Epic selection button click.

    Called when user clicks one of the Epic selection buttons in the selector UI.
    Binds the session to the selected Epic and posts a session card.
    """
    ack()

    epic_key = action.get("value")
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    team_id = body["team"]["id"]

    logger.info(
        "Epic selection received",
        extra={
            "epic_key": epic_key,
            "channel": channel,
            "thread_ts": thread_ts,
        }
    )

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    if epic_key == "new":
        # User wants to create new Epic
        # For now, create a placeholder - full creation in Phase 7
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Creating new Epic... (This will create a Jira Epic in Phase 7)",
        )
        return

    # Bind to selected Epic
    from src.slack.binding import bind_epic
    from src.db.session_store import SessionStore
    from src.db.connection import get_connection

    async with get_connection() as conn:
        store = SessionStore(conn)
        await bind_epic(identity, epic_key, store, client)


def handle_epic_selection_sync(ack, body, client: WebClient, action):
    """Synchronous wrapper for handle_epic_selection.

    Bolt may call handlers from a sync context. This wraps the async handler.
    """
    ack()

    # Run the async handler in background thread with its own event loop
    _run_async(_handle_epic_selection_async(body, client, action))


async def _handle_epic_selection_async(body, client: WebClient, action):
    """Async implementation of epic selection handling."""
    epic_key = action.get("value")
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    team_id = body["team"]["id"]

    logger.info(
        "Epic selection received",
        extra={
            "epic_key": epic_key,
            "channel": channel,
            "thread_ts": thread_ts,
        }
    )

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    if epic_key == "new":
        # User wants to create new Epic
        # For now, create a placeholder - full creation in Phase 7
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Creating new Epic... (This will create a Jira Epic in Phase 7)",
        )
        return

    # Bind to selected Epic
    from src.slack.binding import bind_epic
    from src.db.session_store import SessionStore
    from src.db.connection import get_connection

    async with get_connection() as conn:
        store = SessionStore(conn)
        await bind_epic(identity, epic_key, store, client)


async def handle_merge_context(ack, body, client, action):
    """Handle 'Merge context' button click.

    Links the related thread in session card and Epic summary.
    """
    ack()

    similar_session_id = action.get("value")
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]

    logger.info(
        f"Merge context requested",
        extra={
            "current_thread": thread_ts,
            "similar_session": similar_session_id,
        }
    )

    # Acknowledge the merge
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Context linked from related thread. I'll consider both discussions when gathering requirements.",
    )

    # TODO: Update session card with linked thread reference
    # TODO: Update Epic summary with cross-reference


async def handle_ignore_dedup(ack, body, client):
    """Handle 'Ignore' button click on dedup suggestion."""
    ack()

    # Just acknowledge - user chose to continue independently
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]

    # Delete the suggestion message
    message_ts = body["message"]["ts"]
    try:
        client.chat_delete(channel=channel, ts=message_ts)
    except Exception:
        pass  # May not have permission to delete


# --- Contradiction Resolution Handlers ---

async def handle_contradiction_conflict(ack, body, client, action):
    """Handle 'Mark as conflict' button - flags both values as conflicting."""
    ack()

    value = action.get("value", "")
    _, data = value.split(":", 1)
    subject, proposed_value, thread_ts = data.split("|")

    channel = body["channel"]["id"]
    message_thread = body["message"].get("thread_ts") or body["message"]["ts"]

    logger.info(
        f"Contradiction marked as conflict",
        extra={"subject": subject, "proposed": proposed_value}
    )

    # TODO: Update constraint status to 'conflicted' in KG
    # TODO: Add to Epic summary as unresolved conflict

    client.chat_postMessage(
        channel=channel,
        thread_ts=message_thread,
        text=f"Marked `{subject}` as having conflicting requirements. This needs team alignment.",
    )


async def handle_contradiction_override(ack, body, client, action):
    """Handle 'Override previous' button - new value supersedes old."""
    ack()

    value = action.get("value", "")
    _, data = value.split(":", 1)
    subject, proposed_value, thread_ts = data.split("|")

    channel = body["channel"]["id"]
    message_thread = body["message"].get("thread_ts") or body["message"]["ts"]

    logger.info(
        f"Contradiction resolved by override",
        extra={"subject": subject, "new_value": proposed_value}
    )

    # TODO: Mark old constraint as 'deprecated'
    # TODO: Mark new constraint as 'accepted'

    client.chat_postMessage(
        channel=channel,
        thread_ts=message_thread,
        text=f"Updated `{subject}` to `{proposed_value}`. Previous value deprecated.",
    )


async def handle_contradiction_both(ack, body, client, action):
    """Handle 'Keep both' button - intentional dual values."""
    ack()

    value = action.get("value", "")
    _, data = value.split(":", 1)
    subject, proposed_value, thread_ts = data.split("|")

    channel = body["channel"]["id"]
    message_thread = body["message"].get("thread_ts") or body["message"]["ts"]

    logger.info(
        f"Contradiction accepted as intentional",
        extra={"subject": subject, "proposed": proposed_value}
    )

    # TODO: Mark both as 'accepted' with note about intentional dual values

    client.chat_postMessage(
        channel=channel,
        thread_ts=message_thread,
        text=f"Noted - keeping both values for `{subject}` as intentional.",
    )


# --- Draft Approval Handlers ---

def handle_approve_draft(ack, body, client: WebClient, action):
    """Synchronous wrapper for draft approval.

    Bolt calls handlers from a sync context. This wraps the async handler.
    """
    ack()
    _run_async(_handle_approve_draft_async(body, client, action))


async def _handle_approve_draft_async(body, client: WebClient, action):
    """Handle 'Approve & Create' button click on draft preview.

    Implements version-checked approval:
    1. Check in-memory dedup (handles Slack retries)
    2. Parse session_id:draft_hash from button value
    3. Check if already approved in DB (duplicate click)
    4. Compute current draft hash and compare
    5. Record approval if valid
    6. Update preview message to show approved state
    """
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    message_ts = body["message"]["ts"]  # Preview message to update
    team_id = body["team"]["id"]
    user_id = body["user"]["id"]

    # Parse session_id:draft_hash from button value
    button_value = action.get("value", "")
    action_id = action.get("action_id", "approve_draft")

    # In-memory dedup for Slack retries and rage-clicks
    from src.slack.dedup import try_process_button
    if not try_process_button(action_id, user_id, button_value):
        # Duplicate click - silently ignore (already processing)
        logger.debug(f"Ignoring duplicate approve click: {button_value}")
        return

    if ":" in button_value:
        session_id, button_hash = button_value.rsplit(":", 1)
    else:
        # Legacy format - just session_id
        session_id = button_value
        button_hash = ""

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    logger.info(
        "Draft approval requested",
        extra={
            "session_id": session_id,
            "button_hash": button_hash,
            "user_id": user_id,
        }
    )

    # Import dependencies
    from src.db import ApprovalStore, get_connection
    from src.skills.preview_ticket import compute_draft_hash
    from src.skills.jira_create import jira_create
    from src.jira.client import JiraService
    from src.config.settings import get_settings

    # Get current draft from runner state (need this early for validation)
    runner = get_runner(identity)
    state = await runner._get_current_state()
    draft = state.get("draft")

    if not draft:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Error: Could not find draft. Please start a new session.",
        )
        return

    # Compute current draft hash
    current_hash = compute_draft_hash(draft)

    # Version check - compare button hash with current draft
    if button_hash and button_hash != current_hash:
        # Draft changed since preview was posted - require re-review
        logger.warning(
            "Draft version mismatch",
            extra={
                "button_hash": button_hash,
                "current_hash": current_hash,
                "session_id": session_id,
            }
        )

        # Post new preview with updated content
        from src.slack.blocks import build_draft_preview_blocks_with_hash
        new_blocks = build_draft_preview_blocks_with_hash(
            draft=draft,
            session_id=session_id,
            draft_hash=current_hash,
        )

        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="The draft has changed since you saw this preview. Please review the updated version:",
            blocks=new_blocks,
        )
        return

    # Check for existing approval and record new one
    async with get_connection() as conn:
        approval_store = ApprovalStore(conn)
        await approval_store.create_tables()  # Ensure table exists

        # Check if already approved for this hash
        hash_to_record = current_hash if current_hash else "no-hash"
        existing = await approval_store.get_approval(session_id, hash_to_record)
        if existing:
            # Already approved - check if Jira ticket was created
            from src.db.jira_operations import JiraOperationStore
            op_store = JiraOperationStore(conn)
            await op_store.create_tables()

            if await op_store.was_already_created(session_id, hash_to_record):
                # Ticket already created - notify with link
                existing_op = await op_store.get_operation(session_id, hash_to_record, "jira_create")
                if existing_op and existing_op.jira_key:
                    settings = get_settings()
                    jira_url = f"{settings.jira_url.rstrip('/')}/browse/{existing_op.jira_key}"
                    client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=f"Ticket was already created: <{jira_url}|{existing_op.jira_key}>",
                    )
                    return

            # Already approved but not created - notify
            approver = existing.approved_by
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"This draft was already approved by <@{approver}>.",
            )
            return

        # Record approval (first wins)
        is_new = await approval_store.record_approval(
            session_id=session_id,
            draft_hash=hash_to_record,
            approved_by=user_id,
            status="approved",
        )

        if not is_new:
            # Race condition - another approval just happened
            approver = await approval_store.get_approver(session_id, hash_to_record)
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"This draft was just approved by <@{approver}>.",
            )
            return

        # Approval recorded - now create Jira ticket
        settings = get_settings()
        jira_service = JiraService(settings)

        # Get Slack permalink for Jira description
        slack_permalink = ""
        try:
            from src.context.jira_linker import JiraLinker
            linker = JiraLinker(client, jira_service)
            slack_permalink = linker.get_thread_permalink(channel, thread_ts)
        except Exception as e:
            logger.warning(f"Failed to get Slack permalink: {e}")

        try:
            create_result = await jira_create(
                session_id=session_id,
                draft=draft,
                approved_by=user_id,
                jira_service=jira_service,
                conn=conn,
                settings=settings,
                slack_permalink=slack_permalink,
            )
        finally:
            await jira_service.close()

    # Handle Jira creation result
    if create_result.success:
        if create_result.was_duplicate:
            # Already created (idempotent return) - just notify
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Ticket was already created: <{create_result.jira_url}|{create_result.jira_key}>",
            )
        else:
            # New creation - update session state
            await runner.handle_approval(approved=True)

            # Update thread pin with ticket link
            try:
                from src.context.jira_linker import JiraLinker
                from src.jira.client import JiraService
                from src.config.settings import get_settings

                settings = get_settings()
                jira = JiraService(settings)

                linker = JiraLinker(client, jira)
                await linker.on_ticket_created(
                    channel_id=channel,
                    thread_ts=thread_ts,
                    ticket_key=create_result.jira_key,
                    ticket_url=create_result.jira_url,
                    existing_pin_ts=None,  # Could track from epic binding if available
                )

                await jira.close()
            except Exception as e:
                logger.warning(f"Failed to update ticket pin: {e}")
                # Non-blocking

            # Update preview message to show created state
            _update_preview_to_created(
                client=client,
                channel=channel,
                message_ts=message_ts,
                draft=draft,
                jira_key=create_result.jira_key,
                jira_url=create_result.jira_url,
                created_by=user_id,
            )

            # Notify in thread with Jira link
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Ticket created: <{create_result.jira_url}|{create_result.jira_key}>",
            )
    else:
        # Creation failed - don't advance state, notify error
        # Update preview to show error state (keep buttons for retry)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Could not create ticket: {create_result.error}",
        )


def _update_preview_to_created(
    client: WebClient,
    channel: str,
    message_ts: str,
    draft: "TicketDraft",
    jira_key: str,
    jira_url: str,
    created_by: str,
) -> None:
    """Update preview message to show created state with Jira link.

    Updates the original preview message to:
    - Show "Ticket Created" header with Jira key
    - Display ticket details (title, problem, etc.)
    - Remove approval buttons
    - Add context: Created by @user with Jira link

    Args:
        client: Slack WebClient
        channel: Channel ID
        message_ts: Preview message timestamp to update
        draft: TicketDraft that was created
        jira_key: Created Jira issue key (e.g., PROJ-123)
        jira_url: URL to the Jira issue
        created_by: User ID who created the ticket
    """
    from datetime import datetime

    blocks = []

    # Header with created status and Jira key
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Ticket Created: {jira_key}",
            "emoji": True
        }
    })

    # Title with Jira link
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*<{jira_url}|{draft.title or 'Untitled'}>*"
        }
    })

    # Problem (abbreviated for created state)
    problem_preview = draft.problem[:200] if draft.problem else "_Not set_"
    if draft.problem and len(draft.problem) > 200:
        problem_preview += "..."
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Problem:*\n{problem_preview}"
        }
    })

    # Acceptance Criteria count
    if draft.acceptance_criteria:
        ac_count = len(draft.acceptance_criteria)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Acceptance Criteria:* {ac_count} item{'s' if ac_count != 1 else ''}"
            }
        })

    # Divider
    blocks.append({"type": "divider"})

    # Context with Jira link and creator
    created_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Created by <@{created_by}> at {created_time} | <{jira_url}|View in Jira>"
            }
        ]
    })

    try:
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text=f"Ticket created: {jira_key}",
            blocks=blocks,
        )
    except Exception as e:
        logger.warning(f"Failed to update preview to created state: {e}")


def _build_approved_preview_blocks(draft: "TicketDraft", approved_by: str) -> list[dict]:
    """Build preview blocks with approval status (no action buttons).

    Used to update the preview message after approval.
    """
    from src.schemas.draft import TicketDraft
    from datetime import datetime

    blocks = []

    # Header with approved status
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Ticket Approved",
            "emoji": True
        }
    })

    # Title
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Title:* {draft.title or '_Not set_'}"
        }
    })

    # Problem
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Problem:*\n{draft.problem or '_Not set_'}"
        }
    })

    # Solution (if present)
    if draft.proposed_solution:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Solution:*\n{draft.proposed_solution}"
            }
        })

    # Acceptance Criteria
    if draft.acceptance_criteria:
        ac_text = "*Acceptance Criteria:*\n"
        for i, ac in enumerate(draft.acceptance_criteria, 1):
            ac_text += f"{i}. {ac}\n"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ac_text
            }
        })

    # Divider
    blocks.append({"type": "divider"})

    # Approval context (instead of buttons)
    approval_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Approved by <@{approved_by}> at {approval_time}"
        }]
    })

    return blocks


def handle_reject_draft(ack, body, client: WebClient, action):
    """Synchronous wrapper for draft rejection.

    Bolt calls handlers from a sync context. This wraps the async handler.
    """
    # Get trigger_id BEFORE ack (needed for modal)
    trigger_id = body.get("trigger_id")
    ack()
    _run_async(_handle_reject_draft_async(body, client, action, trigger_id))


async def _handle_reject_draft_async(body, client: WebClient, action, trigger_id):
    """Handle 'Needs Changes' button click on draft preview.

    Opens the edit modal for direct draft editing.
    Implements idempotent rejection handling:
    1. Check in-memory dedup (handles Slack retries)
    2. Open edit modal with current draft values
    """
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    message_ts = body["message"]["ts"]  # Preview message to update later
    team_id = body["team"]["id"]
    user_id = body["user"]["id"]

    # Parse button value (session_id:draft_hash)
    button_value = action.get("value", "")
    action_id = action.get("action_id", "reject_draft")

    # In-memory dedup for Slack retries and rage-clicks
    from src.slack.dedup import try_process_button
    if not try_process_button(action_id, user_id, button_value):
        # Duplicate click - silently ignore
        logger.debug(f"Ignoring duplicate reject click: {button_value}")
        return

    # Parse session_id and draft_hash from button value
    if ":" in button_value:
        session_id, draft_hash = button_value.rsplit(":", 1)
    else:
        session_id = button_value
        draft_hash = ""

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    logger.info(
        "Opening edit modal for draft changes",
        extra={
            "session_id": identity.session_id,
            "user_id": user_id,
        }
    )

    # Get current draft from runner state
    runner = get_runner(identity)
    state = await runner._get_current_state()
    draft = state.get("draft")

    if not draft:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Error: Could not find draft. Please start a new session.",
        )
        return

    # Build and open edit modal
    from src.slack.modals import build_edit_draft_modal
    from src.skills.preview_ticket import compute_draft_hash

    current_hash = compute_draft_hash(draft)
    modal_view = build_edit_draft_modal(
        draft=draft,
        session_id=session_id,
        draft_hash=current_hash,
        preview_message_ts=message_ts,
    )

    try:
        client.views_open(
            trigger_id=trigger_id,
            view=modal_view,
        )
    except Exception as e:
        logger.error(f"Failed to open edit modal: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Sorry, I couldn't open the edit form. Please tell me what needs to be changed in the thread.",
        )


def handle_edit_draft_submit(ack, body, client: WebClient, view):
    """Synchronous wrapper for edit modal submission.

    Bolt calls handlers from a sync context. This wraps the async handler.
    """
    ack()
    _run_async(_handle_edit_draft_submit_async(body, client, view))


async def _handle_edit_draft_submit_async(body, client: WebClient, view):
    """Handle edit modal submission.

    Process modal submission flow:
    1. Parse submitted values from view state
    2. Parse private_metadata for session info
    3. Update draft in runner state
    4. Get updated draft and compute new hash
    5. Update original preview message with new draft
    6. Post confirmation message
    """
    user_id = body["user"]["id"]
    view_state = view.get("state", {}).get("values", {})
    private_metadata_raw = view.get("private_metadata", "{}")

    # Parse private metadata
    import json
    try:
        private_metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse private_metadata: {private_metadata_raw}")
        return

    session_id = private_metadata.get("session_id", "")
    preview_message_ts = private_metadata.get("preview_message_ts", "")

    logger.info(
        "Processing edit modal submission",
        extra={
            "session_id": session_id,
            "user_id": user_id,
        }
    )

    # Parse session_id to get identity parts
    # Format: team:channel:thread_ts
    parts = session_id.split(":")
    if len(parts) != 3:
        logger.error(f"Invalid session_id format: {session_id}")
        return

    team_id, channel, thread_ts = parts

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Parse submitted values
    from src.slack.modals import parse_modal_values
    values = parse_modal_values(view_state)

    # Get runner and current draft
    runner = get_runner(identity)
    state = await runner._get_current_state()
    draft = state.get("draft")

    if not draft:
        logger.error(f"No draft found for session: {session_id}")
        return

    # Update draft with new values
    from src.schemas.draft import DraftConstraint, ConstraintStatus

    # Update basic fields
    if "title" in values:
        draft.title = values["title"]
    if "problem" in values:
        draft.problem = values["problem"]
    if "proposed_solution" in values:
        draft.proposed_solution = values["proposed_solution"]
    if "acceptance_criteria" in values:
        draft.acceptance_criteria = values["acceptance_criteria"]
    if "risks" in values:
        draft.risks = values["risks"]

    # Update constraints (parse key=value pairs)
    if "constraints_raw" in values:
        new_constraints = []
        for c in values["constraints_raw"]:
            new_constraints.append(DraftConstraint(
                key=c["key"],
                value=c["value"],
                status=ConstraintStatus.PROPOSED,
            ))
        draft.constraints = new_constraints

    # Increment version
    draft.version += 1

    # Update runner state with modified draft
    await runner._update_draft(draft)

    # Compute new hash
    from src.skills.preview_ticket import compute_draft_hash
    new_hash = compute_draft_hash(draft)

    # Update original preview message with new draft
    from src.slack.blocks import build_draft_preview_blocks_with_hash
    new_blocks = build_draft_preview_blocks_with_hash(
        draft=draft,
        session_id=session_id,
        draft_hash=new_hash,
    )

    try:
        client.chat_update(
            channel=channel,
            ts=preview_message_ts,
            text=f"Updated ticket preview for: {draft.title or 'Untitled'}",
            blocks=new_blocks,
        )
    except Exception as e:
        logger.warning(f"Failed to update preview message: {e}")

    # Post confirmation
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Draft updated by <@{user_id}>. Please review the changes above.",
    )


def _build_rejected_preview_blocks(draft: "TicketDraft", rejected_by: str) -> list[dict]:
    """Build preview blocks with rejection status (no action buttons).

    Used to update the preview message after rejection.
    """
    from src.schemas.draft import TicketDraft
    from datetime import datetime

    blocks = []

    # Header with rejected status
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Changes Requested",
            "emoji": True
        }
    })

    # Title
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Title:* {draft.title or '_Not set_'}"
        }
    })

    # Problem (abbreviated)
    problem_preview = draft.problem[:100] if draft.problem else "_Not set_"
    if draft.problem and len(draft.problem) > 100:
        problem_preview += "..."
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Problem:* {problem_preview}"
        }
    })

    # Divider
    blocks.append({"type": "divider"})

    # Rejection context (instead of buttons)
    rejection_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Changes requested by <@{rejected_by}> at {rejection_time}"
        }]
    })

    return blocks


# --- MARO Slash Command Handlers ---

def handle_maro_command(ack: Ack, command: dict, say, client: WebClient):
    """Handle /maro slash command (sync wrapper).

    Routes to subcommands: enable, disable, status.
    Delegates to async implementation via _run_async().
    """
    ack()  # Ack immediately
    _run_async(_handle_maro_command_async(command, say, client))


async def _handle_maro_command_async(command: dict, say, client: WebClient):
    """Async implementation of /maro slash command.

    Subcommands:
    - /maro enable - Enable listening in channel
    - /maro disable - Disable listening in channel
    - /maro status - Show current listening state
    """
    channel = command.get("channel_id")
    team_id = command.get("team_id", "")
    user_id = command.get("user_id")
    text = command.get("text", "").strip().lower()

    logger.info(
        "MARO command received",
        extra={
            "channel": channel,
            "team_id": team_id,
            "user_id": user_id,
            "subcommand": text,
        }
    )

    if text == "enable":
        await _handle_maro_enable(team_id, channel, user_id, say)
    elif text == "disable":
        await _handle_maro_disable(team_id, channel, say)
    elif text == "status":
        await _handle_maro_status(team_id, channel, say)
    else:
        say(
            text="*Usage:* `/maro enable | disable | status`\n\n"
                 "- `enable` - Start listening in this channel to maintain context\n"
                 "- `disable` - Stop listening in this channel\n"
                 "- `status` - Show current listening state",
            channel=channel,
        )


async def _handle_maro_enable(
    team_id: str,
    channel_id: str,
    user_id: str,
    say,
):
    """Handle /maro enable - enable listening in channel."""
    from src.db import get_connection, ListeningStore

    try:
        async with get_connection() as conn:
            store = ListeningStore(conn)
            await store.create_tables()  # Ensure table exists
            state = await store.enable(team_id, channel_id, user_id)

        say(
            text="MARO is now listening in this channel to maintain context. "
                 "It won't reply unless mentioned or commanded.",
            channel=channel_id,
        )
        logger.info(
            "Listening enabled",
            extra={
                "team_id": team_id,
                "channel_id": channel_id,
                "enabled_by": user_id,
            }
        )
    except Exception as e:
        logger.error(f"Failed to enable listening: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't enable listening. Please try again.",
            channel=channel_id,
        )


async def _handle_maro_disable(
    team_id: str,
    channel_id: str,
    say,
):
    """Handle /maro disable - disable listening in channel."""
    from src.db import get_connection, ListeningStore

    try:
        async with get_connection() as conn:
            store = ListeningStore(conn)
            state = await store.disable(team_id, channel_id)

        if state:
            say(
                text="MARO has stopped listening in this channel. "
                     "Conversation context will no longer be tracked.",
                channel=channel_id,
            )
        else:
            say(
                text="Listening was not enabled in this channel.",
                channel=channel_id,
            )
        logger.info(
            "Listening disabled",
            extra={"team_id": team_id, "channel_id": channel_id}
        )
    except Exception as e:
        logger.error(f"Failed to disable listening: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't disable listening. Please try again.",
            channel=channel_id,
        )


async def _handle_maro_status(
    team_id: str,
    channel_id: str,
    say,
):
    """Handle /maro status - show current listening state."""
    from src.db import get_connection, ListeningStore

    try:
        async with get_connection() as conn:
            store = ListeningStore(conn)
            state = await store.get_state(team_id, channel_id)

        if not state:
            say(
                text="*MARO Listening Status:* Disabled\n\n"
                     "Use `/maro enable` to start listening in this channel.",
                channel=channel_id,
            )
        elif not state.enabled:
            say(
                text="*MARO Listening Status:* Disabled\n\n"
                     "Use `/maro enable` to start listening in this channel.",
                channel=channel_id,
            )
        else:
            # Build status message
            status_parts = ["*MARO Listening Status:* Enabled"]

            if state.enabled_at:
                enabled_time = state.enabled_at.strftime("%Y-%m-%d %H:%M UTC")
                status_parts.append(f"- Enabled at: {enabled_time}")

            if state.enabled_by:
                status_parts.append(f"- Enabled by: <@{state.enabled_by}>")

            if state.last_summary_at:
                summary_time = state.last_summary_at.strftime("%Y-%m-%d %H:%M UTC")
                status_parts.append(f"- Last summary at: {summary_time}")

            buffer_size = len(state.raw_buffer) if state.raw_buffer else 0
            status_parts.append(f"- Buffer size: {buffer_size} messages")

            say(
                text="\n".join(status_parts),
                channel=channel_id,
            )
    except Exception as e:
        logger.error(f"Failed to get listening status: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't retrieve the listening status. Please try again.",
            channel=channel_id,
        )
