"""Miscellaneous handlers: Epic selection, contradictions, message events.

Contains handlers that don't fit cleanly into other categories.
"""

import logging

from slack_bolt import BoltContext
from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner
from src.slack.handlers.core import _run_async
from src.slack.handlers.attachments import handle_message_files

logger = logging.getLogger(__name__)


def handle_message(event: dict, say, client: WebClient, context: BoltContext):
    """Handle message events for listening and thread participation.

    Two responsibilities:
    1. Update rolling context for listening-enabled channels (all messages)
    2. Process thread messages where bot is already participating

    Skips:
    - Bot messages
    - Message edits/deletes
    """
    # Debug: Log all incoming message events
    logger.info(
        "Message event received",
        extra={
            "channel": event.get("channel"),
            "thread_ts": event.get("thread_ts"),
            "subtype": event.get("subtype"),
            "has_bot_id": bool(event.get("bot_id")),
            "text_preview": (event.get("text") or "")[:50],
        }
    )

    # Skip bot messages
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    # Skip message edits/deletes
    subtype = event.get("subtype")
    if subtype in ("message_changed", "message_deleted"):
        return

    channel = event.get("channel")
    team_id = context.get("team_id", "")

    # Process any attached files (Phase 34)
    files = event.get("files", [])
    if files:
        _run_async(_process_message_files(event, files))

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
    else:
        # No active session in memory - check for persistent state or bot mention
        should_process = False
        process_reason = ""

        # Check 1: Bot mention in message
        from src.config.settings import get_settings
        settings = get_settings()
        bot_user_id = getattr(settings, "slack_bot_user_id", None)
        if bot_user_id and f"<@{bot_user_id}>" in text:
            should_process = True
            process_reason = "bot mention in thread"

        # Check 2: Active checkpoint exists for this thread (sync DB query)
        if not should_process:
            try:
                import psycopg
                from src.config import get_settings
                settings = get_settings()
                session_id = f"{team_id}:{channel}:{thread_ts}"

                # Sync query to check if checkpoint exists with review data
                with psycopg.connect(settings.database_url) as conn:
                    with conn.cursor() as cur:
                        # Check LangGraph checkpoints table for this thread_id
                        cur.execute(
                            """
                            SELECT 1 FROM checkpoints
                            WHERE thread_id = %s
                            AND (checkpoint::text LIKE '%%review_context%%'
                                 OR checkpoint::text LIKE '%%review_artifact%%')
                            LIMIT 1
                            """,
                            (session_id,)
                        )
                        has_review = cur.fetchone() is not None

                if has_review:
                    should_process = True
                    process_reason = "active review in checkpoint"
            except Exception as e:
                logger.debug(f"Could not check checkpoint: {e}")

        if should_process:
            logger.info(
                f"Processing thread message without active session: {process_reason}",
                extra={"channel": channel, "thread_ts": thread_ts},
            )
            # Import and call the mention handler directly
            from src.slack.handlers.core import _process_mention
            _run_async(_process_mention(identity, text, user, client, thread_ts, channel))


async def _process_message_files(event: dict, files: list[dict]) -> None:
    """Process file attachments in a message.

    Registers supported files as Attachments for extraction pipeline.

    Args:
        event: Message event payload.
        files: List of file objects from event["files"].
    """
    try:
        registered_files = await handle_message_files(event, files)
        if registered_files:
            logger.info(f"Registered {len(registered_files)} files from message")
    except Exception as e:
        # Non-blocking - log and continue
        logger.warning(f"Failed to process message files: {e}")


async def _update_listening_context(
    team_id: str,
    channel_id: str,
    message: dict,
) -> bool:
    """Update rolling summary for listening-enabled channel.

    Maintains the two-layer context pattern:
    - Adds new message to raw buffer
    - When buffer exceeds 30, compresses older messages into summary

    This runs for EVERY message in enabled channels, so kept lightweight.
    Summary updates only happen when buffer threshold is exceeded.

    Also checks for high-confidence actionable content (Phase 27.6 noise filter).
    Returns True if MARO should proactively respond.

    Args:
        team_id: Slack team/workspace ID
        channel_id: Channel ID
        message: Slack message dict to add to buffer

    Returns:
        True if message contains high-confidence actionable content
    """
    from src.db import get_connection, ListeningStore
    from src.slack.summarizer import update_rolling_summary, should_update_summary
    from src.slack.noise_filter import should_respond
    from src.llm import get_llm
    from src.config import get_settings

    is_actionable = False
    text = message.get("text", "")

    try:
        # Get bot user ID for noise filter
        settings = get_settings()
        bot_user_id = getattr(settings, "slack_bot_user_id", "BOT")

        async with get_connection() as conn:
            store = ListeningStore(conn)

            # Quick check if listening enabled (lightweight)
            if not await store.is_enabled(team_id, channel_id):
                return False  # Not listening, skip

            # Check if we should respond in listening mode (Phase 27.6)
            respond, reason = should_respond(
                message_text=text,
                bot_user_id=bot_user_id,
                is_listening_mode=True,
                has_pending_action=False,  # No pending action context here
            )

            if respond and reason == "high_confidence_actionable":
                is_actionable = True
                logger.debug(
                    "High-confidence actionable content detected in listening mode",
                    extra={
                        "channel_id": channel_id,
                        "text_preview": text[:100] if text else "",
                        "reason": reason,
                    }
                )

            # Get current state
            summary, raw_buffer = await store.get_summary(team_id, channel_id)

            # Add new message to buffer
            raw_buffer = raw_buffer or []
            raw_buffer.append({
                "user": message.get("user", "unknown"),
                "text": text,
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

    return is_actionable


async def _process_thread_message(
    identity: SessionIdentity,
    text: str,
    user: str,
    client: WebClient,
    thread_ts: str,
    channel: str,
):
    """Async processing for thread message - continues graph and dispatches to skills."""
    from src.slack.progress import ProgressTracker
    from src.slack.handlers.core import _build_conversation_context, _check_persona_switch
    from src.slack.handlers.dispatch import _dispatch_result

    # Create progress tracker for timing-based status feedback
    tracker = ProgressTracker(client, channel, thread_ts)

    try:
        await tracker.start("Processing...")

        runner = get_runner(identity)

        # Check for active review_context - treat as REVIEW_CONTINUATION (Phase 20)
        state = await runner._get_current_state()
        review_context = state.get("review_context")

        if review_context:
            logger.info("Active review_context found - forcing REVIEW_CONTINUATION intent")
            # Force intent to REVIEW_CONTINUATION
            state["intent_result"] = {
                "intent": "REVIEW_CONTINUATION",
                "confidence": 1.0,
                "reasons": ["event_router: active review_context detected"],
            }
            await runner.graph.aupdate_state(runner._config, state)

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

        # Use dispatcher for skill execution (dispatcher handles status updates)
        await _dispatch_result(result, identity, client, runner, tracker)

    except Exception as e:
        logger.error(f"Error processing thread message: {e}", exc_info=True)
    finally:
        await tracker.complete()


# --- Epic Selection Handlers ---

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
    from src.db.workitem_store import WorkItemStore
    from src.db.connection import get_connection

    async with get_connection() as conn:
        store = WorkItemStore(conn)
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
    from src.db.workitem_store import WorkItemStore
    from src.db.connection import get_connection

    async with get_connection() as conn:
        store = WorkItemStore(conn)
        await bind_epic(identity, epic_key, store, client)


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

    # See .planning/ISSUES.md ISS-007, ISS-008

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

    # See .planning/ISSUES.md ISS-009, ISS-010

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

    # See .planning/ISSUES.md ISS-011

    client.chat_postMessage(
        channel=channel,
        thread_ts=message_thread,
        text=f"Noted - keeping both values for `{subject}` as intentional.",
    )
