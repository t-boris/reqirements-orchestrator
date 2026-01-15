"""Custom LangGraph for PM-machine workflow.

Graph structure:
  START -> intent_router -> {ticket_flow | review_flow | discussion_flow}

  ticket_flow: extraction -> should_continue -> validation -> decision -> END
  review_flow: review -> END (persona-based architectural analysis)
  discussion_flow: discussion -> END (brief conversational response)

Intent classification:
  - TICKET: User wants Jira ticket created
  - REVIEW: User wants analysis/review without Jira
  - DISCUSSION: Casual conversation, single response

Guardrails:
  - ReviewFlow and DiscussionFlow do NOT access Jira
  - jira_search, jira_create blocked at code level
  - Override only via explicit mode switch to TicketFlow

Within ticket_flow:
  extraction -> should_continue -> validation -> decision -> (ask: END, preview: END, ready: END)
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
from src.graph.intent import intent_router_node
from src.graph.nodes.extraction import extraction_node
from src.graph.nodes.validation import validation_node
from src.graph.nodes.decision import decision_node, get_decision_action
from src.graph.nodes.discussion import discussion_node
from src.graph.nodes.review import review_node
from src.graph.nodes.ticket_action import ticket_action_node
from src.graph.nodes.decision_approval import decision_approval_node

logger = logging.getLogger(__name__)

MAX_STEPS = 10


def should_continue(state: AgentState) -> Literal["extraction", "validation", "end"]:
    """Router: decide next step based on state.

    Routes to:
    - "end" if intro/nudge set (empty draft response)
    - "end" if max_steps reached (loop protection)
    - "validation" if draft exists and has content
    - "extraction" to continue collecting
    """
    step_count = state.get("step_count", 0)
    draft = state.get("draft")
    decision_result = state.get("decision_result", {})

    # If extraction set intro/nudge, stop and send response
    if decision_result.get("action") in ["intro", "nudge"]:
        logger.info(f"Draft empty, sending {decision_result.get('action')}")
        return "end"

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


def route_after_intent(state: AgentState) -> Literal["ticket_flow", "review_flow", "discussion_flow", "ticket_action_flow", "decision_approval_flow"]:
    """Route based on classified intent.

    Used as conditional edge from intent_router node.
    Routes to appropriate flow based on intent classification.
    """
    intent_result = state.get("intent_result", {})
    intent = intent_result.get("intent", "TICKET")

    if intent == "REVIEW":
        logger.info("Intent router: routing to review_flow")
        return "review_flow"
    elif intent == "DISCUSSION":
        logger.info("Intent router: routing to discussion_flow")
        return "discussion_flow"
    elif intent == "TICKET_ACTION":
        logger.info("Intent router: routing to ticket_action_flow")
        return "ticket_action_flow"
    elif intent == "DECISION_APPROVAL":
        logger.info("Intent router: routing to decision_approval_flow")
        return "decision_approval_flow"
    else:
        logger.info("Intent router: routing to ticket_flow")
        return "ticket_flow"


def create_graph() -> StateGraph:
    """Create the PM-machine workflow graph.

    Returns uncompiled StateGraph. Call .compile() with checkpointer.

    Graph structure:
      START -> intent_router -> {ticket_flow | review_flow | discussion_flow}

      ticket_flow: extraction -> validation -> decision -> END
      review_flow: review -> END
      discussion_flow: discussion -> END

    Intent classification:
      - TICKET: User wants Jira ticket created
      - REVIEW: User wants analysis/review without Jira
      - DISCUSSION: Casual conversation, single response

    Guardrails:
      - ReviewFlow and DiscussionFlow do NOT access Jira
      - jira_search, jira_create blocked at code level
      - Override only via explicit mode switch to TicketFlow
    """
    # Create graph with AgentState
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("intent_router", intent_router_node)
    workflow.add_node("extraction", extraction_node)
    workflow.add_node("validation", validation_node)
    workflow.add_node("decision", decision_node)
    workflow.add_node("discussion", discussion_node)
    workflow.add_node("review", review_node)
    workflow.add_node("ticket_action", ticket_action_node)
    workflow.add_node("decision_approval", decision_approval_node)

    # Set entry point to intent_router
    workflow.set_entry_point("intent_router")

    # Route from intent_router based on classified intent
    workflow.add_conditional_edges(
        "intent_router",
        route_after_intent,
        {
            "ticket_flow": "extraction",  # Existing ticket creation flow
            "review_flow": "review",      # Review generates persona-based analysis
            "discussion_flow": "discussion",  # Discussion generates brief response
            "ticket_action_flow": "ticket_action",  # Work with existing ticket
            "decision_approval_flow": "decision_approval",  # User approved a review (Phase 14)
        }
    )

    # Discussion goes directly to END after generating response
    workflow.add_edge("discussion", END)

    # Review goes directly to END after generating analysis
    workflow.add_edge("review", END)

    # Ticket action goes directly to END after setting up action
    workflow.add_edge("ticket_action", END)

    # Decision approval goes directly to END after packaging for handler
    workflow.add_edge("decision_approval", END)

    # Ticket flow: extraction -> should_continue -> validation -> decision -> END
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


_compiled_graph = None


async def get_compiled_graph():
    """Get compiled graph with PostgreSQL checkpointer.

    Use this for production - enables interrupt/resume.
    Uses singleton pattern for async checkpointer.
    """
    global _compiled_graph

    if _compiled_graph is None:
        from src.db.checkpointer import get_checkpointer
        workflow = create_graph()
        checkpointer = await get_checkpointer()
        _compiled_graph = workflow.compile(checkpointer=checkpointer)
        logger.info("Graph compiled with AsyncPostgresSaver checkpointer")

    return _compiled_graph


# Convenience: graph without checkpointer for testing
def get_graph_for_testing():
    """Get compiled graph without checkpointer.

    Use for unit tests where persistence not needed.
    """
    workflow = create_graph()
    return workflow.compile()
