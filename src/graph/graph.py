"""
LangGraph Graph Definition - Composes nodes into the requirements workflow.

This module defines the state graph with all nodes, edges, and conditional routing.
The graph implements the reflexion pattern with human-in-the-loop approval.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from src.config.settings import get_settings
from src.graph.nodes import (
    conflict_detection_node,
    critique_node,
    draft_node,
    human_approval_node,
    intent_classifier_node,
    jira_write_node,
    memory_node,
    memory_update_node,
    no_response_node,
    process_human_decision_node,
    response_node,
)
from src.graph.state import HumanDecision, IntentType, RequirementState

settings = get_settings()


# =============================================================================
# Conditional Edge Functions
# =============================================================================


def should_respond_router(state: RequirementState) -> str:
    """
    Route based on whether bot should respond.

    Returns:
        "process" if bot should respond, "silent" otherwise.
    """
    if state.get("should_respond", False):
        return "process"
    return "silent"


def intent_router(state: RequirementState) -> str:
    """
    Route based on classified intent type.

    Returns:
        Node name to route to based on intent.
    """
    intent = state.get("intent")

    if intent == IntentType.REQUIREMENT.value:
        return "draft"
    elif intent == IntentType.JIRA_SYNC.value:
        return "jira_write"
    elif intent == IntentType.JIRA_READ.value:
        return "jira_read"
    elif intent == IntentType.QUESTION.value:
        return "respond"
    elif intent == IntentType.OFF_TOPIC.value:
        return "respond"
    else:
        # General or unknown - respond normally
        return "respond"


def critique_router(state: RequirementState) -> str:
    """
    Route based on critique results.

    Implements the reflexion loop: if critique has feedback and we haven't
    exceeded max iterations, go back to draft. Otherwise proceed to approval.

    Returns:
        "refine" to loop back, "approve" to proceed to human approval.
    """
    iteration_count = state.get("iteration_count", 0)
    critique_feedback = state.get("critique_feedback", [])

    # Check if we need to refine
    if critique_feedback and iteration_count < settings.max_reflexion_iterations:
        return "refine"

    # Passed critique or max iterations reached
    return "approve"


def human_decision_router(state: RequirementState) -> str:
    """
    Route based on human decision after approval request.

    Returns:
        Next action based on approve/edit/reject decision.
    """
    decision = state.get("human_decision", HumanDecision.PENDING.value)

    if decision in (HumanDecision.APPROVE.value, HumanDecision.APPROVE_ALWAYS.value):
        return "write_jira"
    elif decision == HumanDecision.EDIT.value:
        return "edit"
    elif decision == HumanDecision.REJECT.value:
        return "reject"
    else:
        # Still pending - shouldn't reach here normally
        return "pending"


def conflict_router(state: RequirementState) -> str:
    """
    Route based on conflict detection results.

    Returns:
        "has_conflicts" if conflicts found, "no_conflicts" otherwise.
    """
    conflicts = state.get("conflicts", [])
    if conflicts:
        return "has_conflicts"
    return "no_conflicts"


# =============================================================================
# Graph Builder
# =============================================================================


def create_graph(checkpointer: BaseCheckpointSaver | None = None) -> StateGraph:
    """
    Create and compile the requirements workflow graph.

    The graph flow:
    1. Memory retrieval -> Intent classification
    2. Intent routing:
       - REQUIREMENT: Draft -> Critique (loop) -> Conflict Detection -> Human Approval -> Jira Write
       - QUESTION/GENERAL: Direct response
       - JIRA_SYNC/JIRA_READ: Jira operations
    3. Memory update and response generation

    Args:
        checkpointer: Optional checkpointer for state persistence.

    Returns:
        Compiled StateGraph ready for execution.
    """
    # Initialize the graph with state schema
    builder = StateGraph(RequirementState)

    # -------------------------------------------------------------------------
    # Add Nodes
    # -------------------------------------------------------------------------

    # Entry point nodes
    builder.add_node("memory", memory_node)
    builder.add_node("intent_classifier", intent_classifier_node)

    # Requirement processing nodes
    builder.add_node("draft", draft_node)
    builder.add_node("critique", critique_node)
    builder.add_node("conflict_detection", conflict_detection_node)

    # Human-in-the-loop nodes
    builder.add_node("human_approval", human_approval_node)
    builder.add_node("process_decision", process_human_decision_node)

    # Jira nodes
    builder.add_node("jira_write", jira_write_node)

    # Memory and response nodes
    builder.add_node("memory_update", memory_update_node)
    builder.add_node("response", response_node)
    builder.add_node("no_response", no_response_node)

    # -------------------------------------------------------------------------
    # Define Edges
    # -------------------------------------------------------------------------

    # Entry point: Start with memory retrieval
    builder.set_entry_point("memory")

    # Memory -> Intent Classification
    builder.add_edge("memory", "intent_classifier")

    # Intent Classification -> Conditional routing based on should_respond
    builder.add_conditional_edges(
        "intent_classifier",
        should_respond_router,
        {
            "process": "route_intent",  # Will be handled by next conditional
            "silent": "no_response",
        },
    )

    # Need an intermediate node for intent routing since we can't chain conditionals directly
    # We'll use a pass-through approach by adding edges from intent_classifier

    # Actually, let's restructure to handle the routing properly
    # After should_respond check, route based on intent

    # -------------------------------------------------------------------------
    # Restructured Flow
    # -------------------------------------------------------------------------

    # Clear and rebuild with proper structure
    builder = StateGraph(RequirementState)

    # Add all nodes
    builder.add_node("memory", memory_node)
    builder.add_node("intent_classifier", intent_classifier_node)
    builder.add_node("draft", draft_node)
    builder.add_node("critique", critique_node)
    builder.add_node("conflict_detection", conflict_detection_node)
    builder.add_node("human_approval", human_approval_node)
    builder.add_node("process_decision", process_human_decision_node)
    builder.add_node("jira_write", jira_write_node)
    builder.add_node("memory_update", memory_update_node)
    builder.add_node("response", response_node)
    builder.add_node("no_response", no_response_node)

    # Set entry point
    builder.set_entry_point("memory")

    # Memory -> Intent
    builder.add_edge("memory", "intent_classifier")

    # Intent -> Conditional based on should_respond and intent type
    def combined_router(state: RequirementState) -> str:
        """Combined router for should_respond and intent."""
        if not state.get("should_respond", False):
            return "no_response"

        intent = state.get("intent")
        if intent == IntentType.REQUIREMENT.value:
            return "draft"
        elif intent == IntentType.JIRA_SYNC.value:
            return "jira_write"
        else:
            return "response"

    builder.add_conditional_edges(
        "intent_classifier",
        combined_router,
        {
            "draft": "draft",
            "jira_write": "jira_write",
            "response": "response",
            "no_response": "no_response",
        },
    )

    # Draft -> Critique
    builder.add_edge("draft", "critique")

    # Critique -> Conditional (refine or proceed)
    builder.add_conditional_edges(
        "critique",
        critique_router,
        {
            "refine": "draft",  # Loop back for refinement
            "approve": "conflict_detection",  # Proceed to conflict check
        },
    )

    # Conflict Detection -> Conditional (notify or proceed)
    builder.add_conditional_edges(
        "conflict_detection",
        conflict_router,
        {
            "has_conflicts": "response",  # Notify user of conflicts
            "no_conflicts": "human_approval",  # Proceed to approval
        },
    )

    # Human Approval is an interrupt point
    # After human makes decision, process it
    builder.add_edge("human_approval", "process_decision")

    # Process Decision -> Conditional routing
    builder.add_conditional_edges(
        "process_decision",
        human_decision_router,
        {
            "write_jira": "jira_write",
            "edit": "draft",  # Back to drafting with feedback
            "reject": "response",  # Respond with rejection message
            "pending": END,  # Edge case - shouldn't happen
        },
    )

    # Jira Write -> Memory Update
    builder.add_edge("jira_write", "memory_update")

    # Memory Update -> Response
    builder.add_edge("memory_update", "response")

    # Terminal nodes
    builder.add_edge("response", END)
    builder.add_edge("no_response", END)

    # -------------------------------------------------------------------------
    # Compile Graph
    # -------------------------------------------------------------------------

    # Compile with interrupt before human_approval for HITL
    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_approval"],  # Pause here for human input
    )

    return graph


# =============================================================================
# Singleton Graph Instance
# =============================================================================

_graph_instance: StateGraph | None = None


async def get_graph() -> StateGraph:
    """
    Get or create the singleton graph instance.

    Uses PostgreSQL checkpointer for state persistence.

    Returns:
        Compiled StateGraph instance.
    """
    global _graph_instance

    if _graph_instance is None:
        from src.graph.checkpointer import get_checkpointer

        checkpointer = await get_checkpointer()
        _graph_instance = create_graph(checkpointer)

    return _graph_instance


async def invoke_graph(
    initial_state: RequirementState,
    thread_id: str,
) -> RequirementState:
    """
    Invoke the graph with initial state.

    This is the main entry point for processing messages.

    Args:
        initial_state: Initial state with message and context.
        thread_id: Unique thread ID for state persistence (channel_id + thread_ts).

    Returns:
        Final state after graph execution.
    """
    graph = await get_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    result = await graph.ainvoke(initial_state, config=config)
    return result


async def resume_graph(
    thread_id: str,
    human_decision: str,
    human_feedback: str | None = None,
) -> RequirementState:
    """
    Resume graph execution after human decision.

    Called after human approves/rejects/edits at the HITL interrupt point.

    Args:
        thread_id: Thread ID of the paused graph.
        human_decision: The human's decision (approve, edit, reject).
        human_feedback: Optional feedback text for edits.

    Returns:
        Final state after resumed execution.
    """
    graph = await get_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    # Update state with human decision
    update = {
        "human_decision": human_decision,
        "human_feedback": human_feedback,
        "awaiting_human": False,
    }

    # Resume from interrupt
    result = await graph.ainvoke(update, config=config)
    return result
