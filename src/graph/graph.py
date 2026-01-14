"""Custom LangGraph for PM-machine workflow.

Graph structure:
  START -> extraction -> should_continue -> validation -> decision -> (ask: END, preview: END, ready: END)
           ^                    |
           |                    v
           +---- loop back ----+

Loop protection:
- max_steps=10 enforced via step_count
- Stops if step_count >= MAX_STEPS
"""
import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from src.schemas.state import AgentState, AgentPhase
from src.graph.nodes.extraction import extraction_node
from src.graph.nodes.validation import validation_node
from src.graph.nodes.decision import decision_node, get_decision_action
from src.db.checkpointer import get_checkpointer

logger = logging.getLogger(__name__)

MAX_STEPS = 10


def should_continue(state: AgentState) -> Literal["extraction", "validation", "end"]:
    """Router: decide next step based on state.

    Routes to:
    - "end" if max_steps reached (loop protection)
    - "validation" if draft exists and has content
    - "extraction" to continue collecting
    """
    step_count = state.get("step_count", 0)
    draft = state.get("draft")
    phase = state.get("phase", AgentPhase.COLLECTING)

    # Loop protection
    if step_count >= MAX_STEPS:
        logger.warning(f"Max steps ({MAX_STEPS}) reached, stopping")
        return "end"

    # If we have a draft with content, move to validation
    if draft and (draft.title or draft.problem):
        return "validation"

    # Continue collecting
    return "extraction"


def route_after_decision(state: AgentState) -> Literal["ask", "preview", "ready"]:
    """Route based on decision result.

    Used as conditional edge from decision node.
    All outcomes currently go to END (Slack handler sends response).
    """
    return get_decision_action(state)


def create_graph() -> StateGraph:
    """Create the PM-machine workflow graph.

    Returns uncompiled StateGraph. Call .compile() with checkpointer.
    """
    # Create graph with AgentState
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("extraction", extraction_node)
    workflow.add_node("validation", validation_node)
    workflow.add_node("decision", decision_node)

    # Set entry point
    workflow.set_entry_point("extraction")

    # Add conditional edges from extraction
    workflow.add_conditional_edges(
        "extraction",
        should_continue,
        {
            "extraction": "extraction",  # Loop back for more extraction
            "validation": "validation",  # Move to validation
            "end": END,  # Stop (max steps)
        }
    )

    # Validation always goes to decision
    workflow.add_edge("validation", "decision")

    # Decision routes to END (Slack handler processes the result)
    # All three outcomes (ask, preview, ready) end the graph run
    # The Slack handler will send appropriate response based on decision_result
    workflow.add_conditional_edges(
        "decision",
        route_after_decision,
        {
            "ask": END,  # ASK: questions sent to user
            "preview": END,  # PREVIEW: draft shown for approval
            "ready": END,  # READY: ticket creation (Phase 7)
        }
    )

    return workflow


def get_compiled_graph():
    """Get compiled graph with PostgreSQL checkpointer.

    Use this for production - enables interrupt/resume.
    """
    workflow = create_graph()
    checkpointer = get_checkpointer()
    return workflow.compile(checkpointer=checkpointer)


# Convenience: graph without checkpointer for testing
def get_graph_for_testing():
    """Get compiled graph without checkpointer.

    Use for unit tests where persistence not needed.
    """
    workflow = create_graph()
    return workflow.compile()
