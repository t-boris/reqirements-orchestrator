"""Scope gate node - handles AMBIGUOUS intent by presenting user choice.

When intent classification returns AMBIGUOUS, this node prepares the state
for the Slack handler to display a 3-button scope gate:
- Review / Analyze
- Create Ticket
- Not now

Plus "Remember for this thread" option to reduce repeated scope gates.
"""
import logging
from typing import Any

from src.schemas.state import AgentState, PendingAction, WorkflowStep

logger = logging.getLogger(__name__)


async def scope_gate_node(state: AgentState) -> dict[str, Any]:
    """Prepare state for scope gate display.

    This node is called when intent is AMBIGUOUS. It:
    1. Sets pending_action to WAITING_SCOPE_CHOICE
    2. Sets workflow_step to appropriate value
    3. Returns decision_result for Slack handler to display scope gate

    The Slack handler will show the 3-button UI and handle responses
    via scope_gate handlers (handle_scope_gate_review, etc.)

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with:
        - decision_result: action="scope_gate" for handler dispatch
        - pending_action: WAITING_SCOPE_CHOICE
        - workflow_step: set for event validation
        - user_message: preserved for re-routing after selection
    """
    from langchain_core.messages import HumanMessage

    # Get latest human message (to preserve for re-routing)
    messages = state.get("messages", [])
    latest_human_message = ""

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    if not latest_human_message:
        logger.warning("No human message found for scope gate")
        latest_human_message = ""

    # Get intent classification reasoning
    intent_result = state.get("intent_result", {})
    intent_reason = ", ".join(intent_result.get("reasons", []))

    logger.info(
        "Scope gate triggered for AMBIGUOUS intent",
        extra={
            "message_preview": latest_human_message[:50] if latest_human_message else "",
            "intent_reason": intent_reason,
        },
    )

    return {
        "decision_result": {
            "action": "scope_gate",
            "message_preview": latest_human_message,
            "intent_reason": intent_reason,
        },
        "pending_action": PendingAction.WAITING_SCOPE_CHOICE,
        "workflow_step": WorkflowStep.DRAFT_PREVIEW,  # Allows scope gate button actions
        "user_message": latest_human_message,  # Preserve for re-routing
    }
