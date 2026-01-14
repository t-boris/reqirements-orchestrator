"""Slack event handlers with fast-ack pattern."""

import logging
from slack_bolt import Ack, BoltContext
from slack_bolt.kwargs_injection.args import Args
from slack_sdk.web import WebClient

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
