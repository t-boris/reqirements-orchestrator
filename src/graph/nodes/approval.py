"""Human approval node."""

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
    WorkflowPhase,
)

from src.graph.nodes.common import logger

# =============================================================================
# Human Approval Node
# =============================================================================

async def human_approval_node(state: RequirementState) -> dict:
    """
    Handle human-in-the-loop approval.

    This node is interrupted before execution to wait for human decision.
    The actual approval UI is handled by Slack handlers.
    """
    print(f"[DEBUG] human_approval_node called - this should NOT appear if interrupt_before works")
    logger.info(
        "awaiting_human_approval",
        channel_id=state.get("channel_id"),
        draft_title=state.get("draft", {}).get("title"),
    )

    # This state signals that we're waiting for human input
    return {
        "awaiting_human": True,
        "human_decision": HumanDecision.PENDING.value,
    }


async def process_human_decision_node(state: RequirementState) -> dict:
    """
    Process the human decision after approval/rejection.

    Routes to appropriate next action based on decision.
    """
    decision = state.get("human_decision", HumanDecision.PENDING.value)

    logger.info(
        "processing_human_decision",
        channel_id=state.get("channel_id"),
        decision=decision,
    )

    if decision == HumanDecision.APPROVE.value:
        return {"awaiting_human": False, "jira_action": "create"}

    elif decision == HumanDecision.APPROVE_ALWAYS.value:
        # Will be handled by approval system to store permanent approval
        return {"awaiting_human": False, "jira_action": "create"}

    elif decision == HumanDecision.EDIT.value:
        # Reset for new iteration with feedback
        return {
            "awaiting_human": False,
            "iteration_count": 0,  # Reset iterations for edit
        }

    elif decision == HumanDecision.REJECT.value:
        return {
            "awaiting_human": False,
            "draft": None,
            "response": "Requirement rejected. Let me know if you'd like to try again.",
        }

    return {"awaiting_human": False}

