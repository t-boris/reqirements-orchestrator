"""Slack event handlers with fast-ack pattern."""

import asyncio
import logging
from slack_bolt import Ack, BoltContext
from slack_bolt.kwargs_injection.args import Args
from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity

logger = logging.getLogger(__name__)


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

    # TODO: Route to session handler in 04-04
    # For now, acknowledge receipt
    say(
        text=f"Got it! I'll help you with this.",
        thread_ts=thread_ts,
    )


def handle_message(event: dict, say, client: WebClient, context: BoltContext):
    """Handle message events in threads where bot is already participating.

    Only processes:
    - Messages in threads (has thread_ts)
    - Non-bot messages
    - Non-edited messages
    """
    # Skip non-thread messages (channel root)
    if "thread_ts" not in event:
        return

    # Skip bot messages
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    # Skip message edits/deletes
    subtype = event.get("subtype")
    if subtype in ("message_changed", "message_deleted"):
        return

    channel = event.get("channel")
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

    # TODO: Check if bot is in this thread session, route to handler
    # For now, log only


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

    # Run the async handler in the event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create a future and run the coroutine
            asyncio.ensure_future(_handle_epic_selection_async(body, client, action))
        else:
            loop.run_until_complete(_handle_epic_selection_async(body, client, action))
    except RuntimeError:
        # No event loop, create one
        asyncio.run(_handle_epic_selection_async(body, client, action))


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
