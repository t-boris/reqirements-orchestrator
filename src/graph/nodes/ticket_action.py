"""Ticket action node - handles operations on existing tickets.

When user mentions an existing ticket (e.g., "create subtasks for SCRUM-1111"),
this node routes the request to the appropriate handler without going through
the full ticket creation flow.

Supports:
- create_subtask: Create subtasks for existing ticket
- update: Update ticket fields
- add_comment: Add comment to ticket
- link: Link current thread to existing ticket
"""
import logging
from typing import Any

from langchain_core.messages import HumanMessage

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


async def ticket_action_node(state: AgentState) -> dict[str, Any]:
    """Handle ticket action intent.

    Reads intent_result to get ticket_key and action_type, then sets up
    decision_result for the handler to process.

    Returns partial state update with decision_result containing:
    - action: "ticket_action"
    - ticket_key: The referenced ticket (e.g., "SCRUM-1111")
    - action_type: The operation to perform
    """
    intent_result = state.get("intent_result", {})
    ticket_key = intent_result.get("ticket_key")
    action_type = intent_result.get("action_type")

    logger.info(
        "Ticket action node processing",
        extra={
            "ticket_key": ticket_key,
            "action_type": action_type,
        }
    )

    # Check thread binding for re-linking prevention
    thread_ts = state.get("thread_ts")
    channel_id = state.get("channel_id")
    already_bound_to_same = False

    if thread_ts and channel_id:
        from src.slack.thread_bindings import get_binding_store

        binding_store = get_binding_store()
        binding = await binding_store.get_binding(channel_id, thread_ts)

        if binding and binding.issue_key == ticket_key:
            # Thread already bound to the SAME ticket - do action, don't re-link
            already_bound_to_same = True
            logger.info(
                "Thread already bound to same ticket",
                extra={
                    "ticket_key": ticket_key,
                    "bound_ticket": binding.issue_key,
                }
            )

    # Get latest human message for content extraction
    messages = state.get("messages", [])
    latest_human_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    return {
        "decision_result": {
            "action": "ticket_action",
            "ticket_key": ticket_key,
            "action_type": action_type,
            "already_bound_to_same": already_bound_to_same,
            "user_message": latest_human_message,  # For content extraction
            "review_context": state.get("review_context"),  # Include if available
        }
    }
