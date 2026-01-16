"""Custom LangGraph for PM-machine workflow.

Graph structure:
  START -> intent_router -> {ticket_flow | review_flow | discussion_flow | scope_gate_flow}

  ticket_flow: extraction -> should_continue -> validation -> decision -> END
  review_flow: review -> END (persona-based architectural analysis)
  discussion_flow: discussion -> END (brief conversational response)
  scope_gate_flow: scope_gate -> END (3-button choice for AMBIGUOUS intent)

Intent classification (pure user intents):
  - TICKET: User wants Jira ticket created
  - REVIEW: User wants analysis/review without Jira
  - DISCUSSION: Casual conversation, single response
  - META: Questions about bot capabilities (routes to discussion)
  - AMBIGUOUS: Intent unclear - triggers scope gate

Note: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION are now
PendingAction values handled by event_router BEFORE graph execution.
They're kept as routes for backward compatibility during migration.

Routing priority:
1. WorkflowEvent (button/slash) - handled before graph (event_router)
2. PendingAction - handled before graph (event_router)
3. Thread default intent - overrides AMBIGUOUS if set
4. Classified intent - route to appropriate flow

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
from src.graph.nodes.review_continuation import review_continuation_node
from src.graph.nodes.ticket_action import ticket_action_node
from src.graph.nodes.decision_approval import decision_approval_node
from src.graph.nodes.scope_gate import scope_gate_node
from src.graph.nodes.jira_command import jira_command_node

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


def route_after_intent(state: AgentState) -> Literal["ticket_flow", "review_flow", "discussion_flow", "ticket_action_flow", "decision_approval_flow", "review_continuation_flow", "scope_gate_flow", "jira_command_flow"]:
    """Route based on classified intent.

    Priority (from 20-CONTEXT.md):
    1. WorkflowEvent - handled before graph (event_router)
    2. PendingAction - handled before graph (event_router)
    3. Thread default intent - check and use for AMBIGUOUS
    4. Classified intent - route to flow

    Note: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION
    are now PendingAction values, handled before this router runs.
    They're kept as routes for backward compatibility during migration.

    Used as conditional edge from intent_router node.
    Routes to appropriate flow based on intent classification.
    """
    intent_result = state.get("intent_result", {})
    intent = intent_result.get("intent", "TICKET")

    # Normalize to uppercase for comparison (scope_gate may set lowercase)
    intent_upper = intent.upper() if isinstance(intent, str) else str(intent).upper()

    # Check for thread default (set by "Remember for this thread")
    thread_default = state.get("thread_default_intent")
    if thread_default and intent_upper == "AMBIGUOUS":
        logger.info(f"Intent router: AMBIGUOUS overridden by thread_default={thread_default}")
        intent_upper = thread_default.upper() if isinstance(thread_default, str) else str(thread_default).upper()

    if intent_upper == "REVIEW":
        logger.info("Intent router: routing to review_flow")
        return "review_flow"
    elif intent_upper == "DISCUSSION":
        logger.info("Intent router: routing to discussion_flow")
        return "discussion_flow"
    elif intent_upper == "META":
        # META questions get brief responses like discussion
        logger.info("Intent router: routing META to discussion_flow")
        return "discussion_flow"
    elif intent_upper == "AMBIGUOUS":
        # Show scope gate - let user decide
        logger.info("Intent router: routing AMBIGUOUS to scope_gate_flow")
        return "scope_gate_flow"
    elif intent_upper == "JIRA_COMMAND":
        # Natural language Jira management commands
        logger.info("Intent router: routing to jira_command_flow")
        return "jira_command_flow"
    elif intent_upper == "TICKET_ACTION":
        # Backward compatibility - these should be PendingActions now
        logger.info("Intent router: routing to ticket_action_flow")
        return "ticket_action_flow"
    elif intent_upper == "DECISION_APPROVAL":
        # Backward compatibility - these should be PendingActions now
        logger.info("Intent router: routing to decision_approval_flow")
        return "decision_approval_flow"
    elif intent_upper == "REVIEW_CONTINUATION":
        # Backward compatibility - these should be PendingActions now
        logger.info("Intent router: routing to review_continuation_flow")
        return "review_continuation_flow"
    else:
        # Default to ticket flow for TICKET intent
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
    workflow.add_node("review_continuation", review_continuation_node)
    workflow.add_node("ticket_action", ticket_action_node)
    workflow.add_node("decision_approval", decision_approval_node)
    workflow.add_node("scope_gate", scope_gate_node)
    workflow.add_node("jira_command", jira_command_node)

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
            "review_continuation_flow": "review_continuation",  # User answered review questions (Phase 15)
            "scope_gate_flow": "scope_gate",  # AMBIGUOUS intent - show scope gate
            "jira_command_flow": "jira_command",  # Natural language Jira commands
        }
    )

    # Discussion goes directly to END after generating response
    workflow.add_edge("discussion", END)

    # Review goes directly to END after generating analysis
    workflow.add_edge("review", END)

    # Review continuation goes directly to END after synthesizing answers
    workflow.add_edge("review_continuation", END)

    # Ticket action goes directly to END after setting up action
    workflow.add_edge("ticket_action", END)

    # Decision approval goes directly to END after packaging for handler
    workflow.add_edge("decision_approval", END)

    # Scope gate goes directly to END (shows UI and waits for button click)
    workflow.add_edge("scope_gate", END)

    # Jira command goes directly to END after setting up confirmation
    workflow.add_edge("jira_command", END)

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
