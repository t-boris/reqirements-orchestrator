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
    from src.schemas.state import ReviewState

    # Get latest human message (the approval)
    messages = state.get("messages", [])
    approval_message = ""

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            approval_message = msg.content
            break

    # Get review context
    review_context = state.get("review_context")

    if not review_context:
        logger.warning("Decision approval called with no review_context")
        return {
            "decision_result": {
                "action": "decision_approval",
                "review_context": None,
                "approval_message": approval_message,
                "user_id": state.get("user_id", "unknown"),
            },
        }

    # Mark as POSTED
    review_context["state"] = ReviewState.POSTED

    # CRITICAL: Freeze review_context → review_artifact before clearing
    # This preserves the architecture for future ticket/epic creation
    import hashlib
    from datetime import datetime, timezone

    # Create canonical artifact from review_context
    review_artifact = {
        "kind": _detect_artifact_kind(review_context.get("persona", "")),
        "version": review_context.get("version", 1),
        "summary": review_context.get("review_summary", ""),
        "updated_summary": review_context.get("updated_recommendation"),  # Latest if patched
        "topic": review_context.get("topic", ""),
        "persona": review_context.get("persona", ""),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "thread_ts": review_context.get("thread_ts", ""),
        "channel_id": review_context.get("channel_id", ""),
        # Hash for idempotency - same content = same hash
        "content_hash": hashlib.sha256(
            (review_context.get("review_summary", "") +
             review_context.get("updated_recommendation", "")).encode()
        ).hexdigest()[:16],
    }

    logger.info(
        "Decision approval: freezing review_context → review_artifact",
        extra={
            "topic": review_artifact["topic"],
            "kind": review_artifact["kind"],
            "version": review_artifact["version"],
            "content_hash": review_artifact["content_hash"],
        }
    )

    # Return with artifact preserved, context cleared
    return {
        "decision_result": {
            "action": "decision_approval",
            "review_context": review_context,  # For handler to post
            "approval_message": approval_message,
            "user_id": state.get("user_id", "unknown"),
        },
        "review_artifact": review_artifact,  # PRESERVED for future use!
        "review_context": None,  # Clear working memory
    }


def _detect_artifact_kind(persona: str) -> str:
    """Map persona to artifact kind."""
    persona_lower = persona.lower() if persona else ""
    if "security" in persona_lower:
        return "security"
    elif "architect" in persona_lower:
        return "architecture"
    elif "pm" in persona_lower or "product" in persona_lower:
        return "pm_review"
    return "architecture"  # Default
