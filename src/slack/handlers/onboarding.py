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

    team_id = event.get("team") or context.get("team_id") or ""

    logger.info(
        "Bot joined channel, posting quick-reference",
        extra={"channel": channel, "channel_type": event.get("channel_type"), "team_id": team_id}
    )

    _run_async(_handle_channel_join_async(channel, team_id, client))


async def _handle_channel_join_async(channel: str, team_id: str, client: WebClient):
    """Async handler for channel join - posts and pins welcome message, creates channel context."""
    from src.slack.blocks import build_welcome_blocks
    from src.db import get_connection
    from src.db.channel_context_store import ChannelContextStore

    logger.info(
        "Building welcome blocks",
        extra={"channel": channel}
    )

    blocks = build_welcome_blocks()

    # Create channel context if it doesn't exist
    try:
        async with get_connection() as conn:
            ctx_store = ChannelContextStore(conn)
            await ctx_store.get_or_create(team_id, channel)
            logger.info(
                "Channel context created/verified",
                extra={"channel": channel, "team_id": team_id}
            )
    except Exception as e:
        logger.warning(f"Could not create channel context: {e}")

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


# --- Scope Source Button Handlers (Fix B) ---

def handle_scope_source(ack, body, client: WebClient, action):
    """Handle scope source button selection.

    When user has actionable intent but draft is empty, we ask where
    to get the architecture/requirements from. This handles their choice.
    """
    ack()
    _run_async(_handle_scope_source_async(body, client, action))


async def _handle_scope_source_async(body, client: WebClient, action):
    """Async handler for scope source selection.

    Routes based on selected source:
    - thread_decisions: Use decisions found in thread
    - pinned_baseline: Use pinned architecture baseline
    - channel_context: Use stored channel decisions
    - describe: Ask user to describe requirements
    """
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    user_id = body["user"]["id"]
    team_id = body["team"]["id"]

    selected = action.get("value", "")

    logger.info(
        "Scope source selected",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "selected": selected,
            "user_id": user_id,
        }
    )

    # Remove the buttons from the original message
    try:
        original_ts = body["message"]["ts"]
        original_blocks = body["message"].get("blocks", [])
        # Keep only non-action blocks
        new_blocks = [b for b in original_blocks if b.get("type") != "actions"]
        # Add selection confirmation
        new_blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"_Selected: {selected.replace('_', ' ').title()}_",
            }]
        })
        client.chat_update(
            channel=channel,
            ts=original_ts,
            blocks=new_blocks,
            text=body["message"].get("text", ""),
        )
    except Exception as e:
        logger.warning(f"Failed to update scope source message: {e}")

    if selected == "describe":
        # User wants to describe requirements manually
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Please describe the requirements or architecture you'd like to turn into work items.",
        )
        return

    # For other options, try to load content and re-run extraction
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    try:
        from src.db.connection import get_connection
        from src.context.reference_resolver import resolve_architecture_reference

        async with get_connection() as conn:
            # Get conversation messages if needed
            conversation_messages = None
            if selected == "thread_decisions":
                # Fetch thread messages
                try:
                    result = client.conversations_replies(
                        channel=channel,
                        ts=thread_ts,
                        limit=50,
                    )
                    conversation_messages = result.get("messages", [])
                except Exception as e:
                    logger.warning(f"Failed to fetch thread messages: {e}")

            bundle = await resolve_architecture_reference(
                conn=conn,
                channel_id=channel,
                thread_ts=thread_ts,
                conversation_messages=conversation_messages,
            )

        if bundle.is_empty():
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f"I couldn't find architecture content from '{selected.replace('_', ' ')}'.\n"
                    "Please describe the requirements or paste the architecture here."
                ),
            )
            return

        # Found content - inject into runner and trigger extraction
        from src.graph.runner import get_runner, _runners

        if identity.session_id in _runners:
            runner = get_runner(identity)

            # Update state with resolved reference
            current_state = await runner._get_current_state()
            updated_state = {
                **current_state,
                "review_artifact": {
                    "summary": bundle.to_context_string(),
                    "source": bundle.source,
                    "decision_count": bundle.decision_count,
                },
            }
            await runner._update_state(updated_state)

            # Notify user
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Found {bundle.decision_count} decision(s) from {bundle.source_description}. Processing...",
            )

            # Re-trigger the graph with the same message
            # The extraction node will now find review_artifact
            from langchain_core.messages import HumanMessage

            messages = current_state.get("messages", [])
            if messages:
                last_msg = messages[-1]
                if isinstance(last_msg, HumanMessage):
                    await runner.process_message(
                        str(last_msg.content),
                        user_id=user_id,
                    )
        else:
            # No active session - just post what we found
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f"Found {bundle.decision_count} decision(s) from {bundle.source_description}.\n"
                    "Please repeat your request to create work items."
                ),
            )

    except Exception as e:
        logger.error(f"Failed to handle scope source selection: {e}")
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Error loading content: {e}. Please describe the requirements manually.",
        )
