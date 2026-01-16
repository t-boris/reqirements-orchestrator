"""Handlers for scope gate interactions.

Handles the 3-button scope gate for AMBIGUOUS intent:
- Review: Route to review flow
- Create ticket: Route to ticket flow
- Not now: Dismiss

Plus "Remember for this thread" checkbox state.
"""
import logging
from datetime import datetime, timedelta

from slack_sdk.web import WebClient

from src.schemas.state import UserIntent, PendingAction, WorkflowStep
from src.slack.blocks.scope_gate import (
    build_scope_gate_dismissed_blocks,
    build_scope_gate_remembered_blocks,
)

logger = logging.getLogger(__name__)

# How long "Remember" lasts (2 hours)
REMEMBER_TTL_HOURS = 2


def handle_scope_gate_review(ack, body: dict, client: WebClient):
    """Handle 'Review' button click on scope gate.

    Routes to review flow. If 'Remember' was checked, stores thread default.
    """
    ack()
    channel = body.get("channel", {}).get("id")
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
    user_id = body.get("user", {}).get("id")

    # Check if remember was selected
    remember = _check_remember_selected(body)

    # Update original message to show selection
    message_ts = body.get("message", {}).get("ts")
    if remember:
        blocks = build_scope_gate_remembered_blocks("review")
    else:
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Routing to review..."}}]

    client.chat_update(
        channel=channel,
        ts=message_ts,
        blocks=blocks,
        text="Routing to review...",
    )

    # Store thread default if remember selected
    if remember:
        _store_thread_default(channel, thread_ts, UserIntent.REVIEW)

    # Re-route to review flow with original message
    _route_to_flow(body, client, UserIntent.REVIEW)


def handle_scope_gate_ticket(ack, body: dict, client: WebClient):
    """Handle 'Create ticket' button click on scope gate.

    Routes to ticket flow. If 'Remember' was checked, stores thread default.
    """
    ack()
    channel = body.get("channel", {}).get("id")
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
    message_ts = body.get("message", {}).get("ts")

    remember = _check_remember_selected(body)

    if remember:
        blocks = build_scope_gate_remembered_blocks("ticket")
    else:
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Creating ticket..."}}]

    client.chat_update(
        channel=channel,
        ts=message_ts,
        blocks=blocks,
        text="Creating ticket...",
    )

    if remember:
        _store_thread_default(channel, thread_ts, UserIntent.TICKET)

    _route_to_flow(body, client, UserIntent.TICKET)


def handle_scope_gate_dismiss(ack, body: dict, client: WebClient):
    """Handle 'Not now' button click on scope gate.

    Clears pending_action and stops cycle.
    """
    ack()
    channel = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")

    blocks = build_scope_gate_dismissed_blocks()
    client.chat_update(
        channel=channel,
        ts=message_ts,
        blocks=blocks,
        text="Got it. Just @ me when you're ready.",
    )

    # Clear any pending action in state
    # This happens via state update in the main handler


def _check_remember_selected(body: dict) -> bool:
    """Check if 'Remember' checkbox was selected.

    The checkbox state is in body.state.values.
    """
    state = body.get("state", {})
    values = state.get("values", {})

    for block_id, block_values in values.items():
        for action_id, action_value in block_values.items():
            if action_id == "scope_gate_remember":
                selected_options = action_value.get("selected_options", [])
                return len(selected_options) > 0

    return False


def _store_thread_default(channel_id: str, thread_ts: str, intent: UserIntent):
    """Store thread default intent with 2h expiry.

    TODO: This will be integrated with state persistence in 20-04.
    For now, log intent for debugging.
    """
    expires_at = datetime.utcnow() + timedelta(hours=REMEMBER_TTL_HOURS)
    logger.info(
        f"Storing thread default: {intent.value} for {channel_id}/{thread_ts}, "
        f"expires {expires_at.isoformat()}"
    )
    # State update will be handled by graph runner


def _route_to_flow(body: dict, client: WebClient, intent: UserIntent):
    """Re-route original message to the selected flow.

    Runs the graph with forced intent (REVIEW or TICKET).
    Uses the user_message saved in state during scope_gate_node.
    """
    import asyncio
    from src.graph.runner import get_runner
    from src.slack.session import SessionIdentity
    from src.slack.handlers.dispatch import _dispatch_result

    logger.info(f"Routing to {intent.value} flow after scope gate selection")

    # Extract identity from body
    channel = body.get("channel", {}).get("id")
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
    team_id = body.get("team", {}).get("id") or body.get("user", {}).get("team_id")
    user_id = body.get("user", {}).get("id")

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel,
        thread_ts=thread_ts,
    )

    async def _run_with_forced_intent():
        runner = get_runner(identity)

        # Get current state to retrieve user_message
        state = await runner._get_current_state()
        user_message = state.get("user_message", "")

        if not user_message:
            logger.warning("No user_message found in state for scope gate routing")
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Sorry, I lost track of your original request. Please try again.",
            )
            return

        # Force the intent in state before running
        forced_intent_result = {
            "intent": intent.value,
            "confidence": 1.0,
            "reasons": [f"scope_gate: user selected {intent.value}"],
        }

        # Update state with forced intent
        state["intent_result"] = forced_intent_result
        state["pending_action"] = None  # Clear pending action
        state["workflow_step"] = None

        await runner.graph.aupdate_state(runner._config, state)

        # Run graph - it will use the forced intent
        result = await runner.run_with_message(user_message, user_id)

        # Dispatch result
        await _dispatch_result(result, identity, client, runner, tracker=None)

    # Run async function from sync context
    from src.slack.handlers.core import _background_loop
    if _background_loop and _background_loop.is_running():
        asyncio.run_coroutine_threadsafe(_run_with_forced_intent(), _background_loop)
    else:
        # Fallback - create new event loop
        asyncio.run(_run_with_forced_intent())
