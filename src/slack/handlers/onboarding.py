"""Channel join, hints, and help example handlers.

Handles onboarding-related interactions including channel join welcome messages,
hint button selections, and help example buttons.
"""

import logging

from slack_bolt import BoltContext
from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner
from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


# --- Channel Join Handler (Phase 12) ---

def handle_member_joined_channel(event: dict, client: WebClient, context: BoltContext):
    """Handle member_joined_channel event - post pinned quick-reference.

    Only triggers when the bot itself joins a channel.
    Posts the welcome message and pins it immediately.

    Pattern: Sync wrapper delegates to async.
    """
    # Log the raw event for debugging
    logger.info(
        "member_joined_channel event received",
        extra={
            "event": event,
            "user": event.get("user"),
            "channel": event.get("channel"),
            "bot_user_id": context.get("bot_user_id"),
        }
    )

    # Only respond to bot's own join
    user = event.get("user")
    bot_user_id = context.get("bot_user_id")

    if user != bot_user_id:
        logger.info(
            "Ignoring member join - not the bot",
            extra={"user": user, "bot_user_id": bot_user_id}
        )
        return  # Not our join, ignore

    channel = event.get("channel")

    logger.info(
        "Bot joined channel, posting quick-reference",
        extra={"channel": channel, "channel_type": event.get("channel_type")}
    )

    _run_async(_handle_channel_join_async(channel, client))


async def _handle_channel_join_async(channel: str, client: WebClient):
    """Async handler for channel join - posts and pins welcome message."""
    from src.slack.blocks import build_welcome_blocks

    logger.info(
        "Building welcome blocks",
        extra={"channel": channel}
    )

    blocks = build_welcome_blocks()

    try:
        # Post the quick-reference message
        logger.info(
            "Posting welcome message to channel",
            extra={"channel": channel, "has_blocks": bool(blocks)}
        )

        result = client.chat_postMessage(
            channel=channel,
            text="MARO is active in this channel",
            blocks=blocks,
            # EXPLICITLY no thread_ts - post to channel root
        )

        message_ts = result.get("ts")

        logger.info(
            "Welcome message posted successfully",
            extra={"channel": channel, "message_ts": message_ts}
        )

        # Pin the message
        if message_ts:
            try:
                logger.info(
                    "Attempting to pin welcome message",
                    extra={"channel": channel, "message_ts": message_ts}
                )

                client.pins_add(
                    channel=channel,
                    timestamp=message_ts,
                )

                logger.info(
                    "Pinned welcome message successfully",
                    extra={"channel": channel, "message_ts": message_ts}
                )
            except Exception as e:
                # May fail if bot lacks pin permission - non-blocking
                logger.warning(
                    f"Could not pin welcome message: {e}",
                    extra={"channel": channel, "error": str(e)}
                )

    except Exception as e:
        logger.error(
            f"Failed to post welcome message: {e}",
            extra={"channel": channel, "error": str(e)},
            exc_info=True
        )


# --- Hint Button Action Handlers (Phase 12 Onboarding) ---

def handle_hint_selection(ack, body, client: WebClient, action):
    """Handle hint button selection (e.g., persona selection from hint).

    Wraps async handler for sync context.
    """
    ack()
    _run_async(_handle_hint_selection_async(body, client, action))


async def _handle_hint_selection_async(body, client: WebClient, action):
    """Async handler for hint button selection.

    Routes to appropriate action based on button value.
    """
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    user_id = body["user"]["id"]

    # Get selected value (e.g., "pm", "architect", "security")
    selected = action.get("value", "")

    logger.info(
        "Hint button selected",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "selected": selected,
            "user_id": user_id,
        }
    )

    # Handle persona selection
    if selected in ["pm", "architect", "security"]:
        # Switch persona
        team_id = body["team"]["id"]
        identity = SessionIdentity(
            team_id=team_id,
            channel_id=channel,
            thread_ts=thread_ts,
        )

        try:
            from src.personas.commands import handle_persona_command

            state = {"persona": "pm", "persona_lock": False}
            result = handle_persona_command(selected, state)

            # Update message to confirm selection
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=result.message,
            )

            # Update runner state if session exists
            from src.graph.runner import _runners
            if identity.session_id in _runners:
                runner = get_runner(identity)
                current_state = await runner._get_current_state()
                if result.state_update:
                    new_state = {**current_state, **result.state_update}
                    await runner._update_state(new_state)

        except Exception as e:
            logger.warning(f"Failed to handle hint persona selection: {e}")
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Switched to {selected} perspective.",
            )


# --- Help Example Button Handlers (Phase 12 Onboarding) ---

def handle_help_example(ack, body, client: WebClient, action):
    """Handle help example button click.

    Shows example conversation for the selected feature.
    """
    ack()

    channel = body["channel"]["id"]
    user_id = body["user"]["id"]

    # Get example key from action_id (help_example_create_ticket -> create_ticket)
    action_id = action.get("action_id", "")
    example_key = action_id.replace("help_example_", "")

    logger.info(
        "Help example requested",
        extra={
            "channel": channel,
            "example_key": example_key,
            "user_id": user_id,
        }
    )

    from src.slack.onboarding import get_example_blocks

    blocks = get_example_blocks(example_key)

    # Post example as ephemeral message (only visible to user who clicked)
    try:
        client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text=f"Example: {example_key.replace('_', ' ').title()}",
            blocks=blocks,
        )
    except Exception as e:
        logger.warning(f"Failed to post ephemeral example: {e}")
        # Fall back to regular message
        client.chat_postMessage(
            channel=channel,
            text=f"Example: {example_key.replace('_', ' ').title()}",
            blocks=blocks,
        )
