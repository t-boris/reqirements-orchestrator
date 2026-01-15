"""Decision approval node - records architecture decisions when user approves a review.

When user says "let's go with this" (or similar) after a review, this node:
1. Retrieves review_context from state
2. Returns action="decision_approval" for handler to process
3. Handler extracts decision summary and posts to channel

This node ONLY packages the state for the handler - actual extraction and
posting happens in handlers.py to keep the graph lightweight.
"""
import logging

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


async def decision_approval_node(state: AgentState) -> dict:
    """LangGraph node for decision approval flow.

    Packages review_context and user info for the handler to process.
    Does NOT do LLM calls or Slack posting - that happens in handler.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with decision_result containing:
        - action: "decision_approval"
        - review_context: The saved review context (or None)
        - approval_message: The user's approval text
        - user_id: Who approved
    """
    from langchain_core.messages import HumanMessage

    # Get latest human message (the approval)
    messages = state.get("messages", [])
    approval_message = ""

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            approval_message = msg.content
            break

    # Get review context
    review_context = state.get("review_context")

    logger.info(
        "Decision approval node processing",
        extra={
            "has_review_context": review_context is not None,
            "approval_preview": approval_message[:50] if approval_message else "",
        }
    )

    # Clear review_context after processing (state update)
    return {
        "decision_result": {
            "action": "decision_approval",
            "review_context": review_context,
            "approval_message": approval_message,
            "user_id": state.get("user_id", "unknown"),
        },
        "review_context": None,  # Clear after processing
    }
