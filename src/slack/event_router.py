"""Event-first routing for Slack events.

Priority order (from 20-CONTEXT.md):
1. Check idempotency (reject duplicates)
2. WorkflowEvent (button/slash) -> handler directly
3. PendingAction -> continuation handler
4. Thread default intent (if "Remember" selected)
5. UserIntent -> classify and route

This separates "what user wants" from "what system is doing".
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.schemas.state import (
    WorkflowEventType,
    WorkflowStep,
    PendingAction,
    UserIntent,
)
from src.graph.event_validation import (
    validate_event,
    validate_ui_version,
    STALE_EVENT_MESSAGE,
    STALE_VERSION_MESSAGE,
    ALREADY_PROCESSED_MESSAGE,
)
from src.db import EventStore, make_button_event_id

logger = logging.getLogger(__name__)


class RouteResult(str, Enum):
    """Result of event routing."""
    WORKFLOW_EVENT = "workflow_event"  # Handle button/slash directly
    CONTINUATION = "continuation"      # Continue pending workflow
    INTENT_CLASSIFY = "intent_classify"  # Run intent classification
    DUPLICATE = "duplicate"            # Already processed
    STALE_UI = "stale_ui"              # Stale button click


@dataclass
class RoutingDecision:
    """Decision from event router."""
    result: RouteResult
    event_action: Optional[str] = None  # For WORKFLOW_EVENT
    pending_action: Optional[PendingAction] = None  # For CONTINUATION
    default_intent: Optional[UserIntent] = None  # For thread default
    error_message: Optional[str] = None  # For DUPLICATE/STALE_UI


def is_workflow_event(body: dict) -> bool:
    """Check if Slack event is a workflow event (button/command/modal).

    Workflow events bypass intent classification entirely.
    """
    # Button click
    if body.get("type") == "block_actions":
        return True
    # Slash command
    if body.get("command"):
        return True
    # Modal submission
    if body.get("type") == "view_submission":
        return True
    return False


def extract_event_info(body: dict) -> tuple[Optional[WorkflowEventType], Optional[str], Optional[int]]:
    """Extract event type, action, and ui_version from Slack event.

    Returns:
        (event_type, action, ui_version) - ui_version may be None
    """
    if body.get("type") == "block_actions":
        actions = body.get("actions", [])
        if actions:
            action = actions[0]
            action_id = action.get("action_id", "")
            # Parse ui_version from action value if present
            # Format: "action_name:ui_version" or just "action_name"
            value = action.get("value", "")
            ui_version = None
            if ":" in str(value):
                parts = str(value).rsplit(":", 1)
                if parts[-1].isdigit():
                    ui_version = int(parts[-1])
            return (WorkflowEventType.BUTTON_CLICK, action_id, ui_version)

    if body.get("command"):
        return (WorkflowEventType.SLASH_COMMAND, body.get("command"), None)

    if body.get("type") == "view_submission":
        callback_id = body.get("view", {}).get("callback_id", "")
        return (WorkflowEventType.MODAL_SUBMIT, callback_id, None)

    return (None, None, None)


async def route_event(
    body: dict,
    team_id: str,
    state: dict,
    event_store: EventStore,
) -> RoutingDecision:
    """Route incoming event using priority order.

    Args:
        body: Slack event body
        team_id: Slack team/workspace ID
        state: Current AgentState dict
        event_store: EventStore for idempotency

    Returns:
        RoutingDecision with result and relevant data
    """
    # Step 0: Check idempotency
    event_id = _get_event_id(body)
    if event_id:
        if await event_store.is_processed(team_id, event_id):
            logger.info(f"Duplicate event rejected: {event_id}")
            return RoutingDecision(
                result=RouteResult.DUPLICATE,
                error_message=ALREADY_PROCESSED_MESSAGE,
            )

    # Step 1: WorkflowEvent (button/slash) -> handler directly
    if is_workflow_event(body):
        event_type, action, ui_version = extract_event_info(body)

        # Validate against current workflow step
        workflow_step = state.get("workflow_step")
        if workflow_step:
            workflow_step = WorkflowStep(workflow_step) if isinstance(workflow_step, str) else workflow_step

            if not validate_event(workflow_step, action):
                return RoutingDecision(
                    result=RouteResult.STALE_UI,
                    error_message=STALE_EVENT_MESSAGE,
                )

            # Check UI version if present
            if ui_version is not None:
                state_ui_version = state.get("ui_version", 0)
                if not validate_ui_version(state_ui_version, ui_version):
                    return RoutingDecision(
                        result=RouteResult.STALE_UI,
                        error_message=STALE_VERSION_MESSAGE,
                    )

        # Mark as processed
        if event_id:
            await event_store.mark_processed(team_id, event_id)

        return RoutingDecision(
            result=RouteResult.WORKFLOW_EVENT,
            event_action=action,
        )

    # Step 2: PendingAction -> continuation handler
    pending_action = state.get("pending_action")
    if pending_action:
        pending_action = PendingAction(pending_action) if isinstance(pending_action, str) else pending_action
        return RoutingDecision(
            result=RouteResult.CONTINUATION,
            pending_action=pending_action,
        )

    # Step 2.5: Active review_context -> treat as REVIEW continuation
    # If there's a review_context, user replies are answers to open questions
    review_context = state.get("review_context")
    if review_context:
        logger.info("Active review_context found - routing as REVIEW continuation")
        return RoutingDecision(
            result=RouteResult.CONTINUATION,
            pending_action=PendingAction.WAITING_APPROVAL,  # Review waiting for answers
        )

    # Step 3: Thread default intent (if "Remember" was selected)
    thread_default = state.get("thread_default_intent")
    if thread_default:
        # Check if expired (2h inactivity)
        expires_at = state.get("thread_default_expires_at")
        if expires_at and not _is_expired(expires_at):
            thread_default = UserIntent(thread_default) if isinstance(thread_default, str) else thread_default
            return RoutingDecision(
                result=RouteResult.INTENT_CLASSIFY,
                default_intent=thread_default,
            )

    # Step 4: UserIntent -> classify and route
    return RoutingDecision(result=RouteResult.INTENT_CLASSIFY)


def _get_event_id(body: dict) -> Optional[str]:
    """Extract or construct event ID for idempotency.

    For button clicks, use action_id:message_ts:user_id as fallback.
    """
    # Try to get event_id from envelope
    if "event_id" in body:
        return body["event_id"]

    # For button clicks, construct fallback key
    if body.get("type") == "block_actions":
        actions = body.get("actions", [])
        if actions:
            action_id = actions[0].get("action_id", "")
            message_ts = body.get("message", {}).get("ts", "")
            user_id = body.get("user", {}).get("id", "")
            if action_id and message_ts and user_id:
                return make_button_event_id(action_id, message_ts, user_id)

    return None


def _is_expired(expires_at: str) -> bool:
    """Check if ISO timestamp is in the past."""
    from datetime import datetime
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(expires.tzinfo) > expires
    except (ValueError, TypeError):
        return True  # Invalid timestamp = expired
