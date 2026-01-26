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
from src.graph.nodes.sync_trigger import sync_trigger_node
from src.graph.nodes.jira_search import jira_search_node
from src.graph.nodes.change_request import change_request_node
from src.graph.nodes.draft_transform import draft_transform_node
from src.graph.nodes.ops import ops_node
from src.graph.nodes.task_decomposer import task_decomposer_node
from src.graph.nodes.task_executor import task_executor_node
from src.graph.nodes.terminal import terminal_response_node, is_terminal_response
from src.graph.intent_gates import GateResult

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


def route_after_decision(state: AgentState) -> Literal["ask", "preview", "ready", "preflight", "draft_refine"]:
    """Route based on decision result.

    Used as conditional edge from decision node.
    All outcomes currently go to END (Slack handler sends response).

    Routes:
    - ask: Need more info from user
    - preview: Show draft for approval (may include likely duplicates)
    - ready: Approved, ready to create in Jira
    - preflight: EXACT_MATCH found, must choose before proceeding
    - draft_refine: User asking about draft structure (Phase 26)
    """
    return get_decision_action(state)


def route_after_decomposer(state: AgentState) -> Literal["task_executor", "end"]:
    """Route after task decomposition.

    If a TaskPlan was created with tasks, route to task_executor.
    Otherwise, route to end (single intent or error case).
    """
    task_plan = state.get("task_plan")
    if task_plan and task_plan.get("tasks"):
        return "task_executor"
    return "end"


def route_after_intent(state: AgentState) -> Literal["ticket_flow", "review_flow", "discussion_flow", "ticket_action_flow", "decision_approval_flow", "review_continuation_flow", "scope_gate_flow", "jira_command_flow", "sync_flow", "change_request_flow", "ops_flow", "jira_search_flow", "draft_transform_flow", "task_decomposer_flow", "terminal_response_flow", "triage_questions_flow", "question_collection_flow"]:
    """Route based on classified intent.

    Priority (from 20-CONTEXT.md):
    1. WorkflowEvent - handled before graph (event_router)
    2. PendingAction - handled before graph (event_router)
    3. Phase 44: Triage gate (incomplete context) - ask clarifying questions
    4. Question collection gate - ask LLM if it has open questions
    5. Phase 39: Terminal intent via envelope (DISCUSSION/META)
    6. Multi-intent detection - route to task_decomposer (Phase 35)
    7. Thread default intent - check and use for AMBIGUOUS
    8. Classified intent - route to flow

    Note: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION
    are now PendingAction values, handled before this router runs.
    They're kept as routes for backward compatibility during migration.

    Phase 35: When multi-intent is detected (is_multi_intent=True in
    task_plan_proposal), route to task_decomposer for plan creation.

    Phase 39: When envelope indicates terminal intent (DISCUSSION/META),
    route to terminal_response_flow for single response then END.

    Phase 44: When stage0_gate returns GateResult.TRIAGE, route to
    triage_questions_flow to post clarifying questions.

    Question Collection: After classification, route to question_collection
    to ask LLM for open questions before proceeding to actual flow.

    Used as conditional edge from intent_router node.
    Routes to appropriate flow based on intent classification.
    """
    # Phase 44: Check for triage gate first (incomplete context)
    stage0_gate = state.get("stage0_gate")
    if stage0_gate and stage0_gate.result == GateResult.TRIAGE:
        logger.info("Intent router: triage needed, routing to triage_questions")
        return "triage_questions_flow"

    # Question Collection Gate: Route to question_collection if not complete
    # Skip for terminal intents, ticket_action, decision_approval (they don't need questions)
    question_collection_complete = state.get("question_collection_complete", False)
    envelope = state.get("envelope")
    skip_question_collection = False

    if envelope:
        from src.graph.intent_router import is_terminal_intent
        # Skip for terminal intents (greetings, meta questions)
        if is_terminal_intent(envelope):
            skip_question_collection = True
        # Skip for action intents that work on existing items
        from src.schemas.intent import IntentKind
        if envelope.intent in (IntentKind.TICKET_ACTION, IntentKind.DECISION_APPROVAL, IntentKind.REVIEW_CONTINUATION):
            skip_question_collection = True

    if not question_collection_complete and not skip_question_collection:
        logger.info("Intent router: routing to question_collection gate")
        return "question_collection_flow"

    intent_result = state.get("intent_result", {})

    # Phase 39: Check for terminal intent via envelope
    envelope = state.get("envelope")
    if envelope:
        from src.graph.intent_router import is_terminal_intent
        if is_terminal_intent(envelope):
            logger.info(f"Intent router: terminal intent detected ({envelope.intent.value}), routing to terminal_response")
            return "terminal_response_flow"

    # Phase 35: Check for multi-intent proposal first
    proposal = intent_result.get("task_plan_proposal")
    if proposal and proposal.get("is_multi_intent"):
        logger.info("Intent router: multi-intent detected, routing to task_decomposer")
        return "task_decomposer_flow"
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
    elif intent_upper == "SYNC_REQUEST":
        # Bulk sync with Jira
        logger.info("Intent router: routing to sync_flow")
        return "sync_flow"
    elif intent_upper == "JIRA_SEARCH":
        # Search Jira for existing issues
        logger.info("Intent router: routing to jira_search_flow")
        return "jira_search_flow"
    elif intent_upper == "OPS":
        # Operational mode - debug failures or explain decisions
        logger.info("Intent router: routing to ops_flow")
        return "ops_flow"
    elif intent_upper == "CHANGE_REQUEST":
        # Diff-based updates to existing truth
        logger.info("Intent router: routing to change_request_flow")
        return "change_request_flow"
    elif intent_upper == "DRAFT_REFINE":
        # Refinement questions about active draft - stays in ticket flow
        logger.info("Intent router: routing DRAFT_REFINE to ticket_flow")
        return "ticket_flow"
    elif intent_upper == "DRAFT_TRANSFORM":
        # Structural transformation of draft
        logger.info("Intent router: routing DRAFT_TRANSFORM to draft_transform_flow")
        return "draft_transform_flow"
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


async def triage_questions_node(state: AgentState) -> dict:
    """Generate and return triage question for posting.

    Phase 44: Questions-First Collection Stage

    Does NOT post to Slack - dispatch handler does that.
    Returns decision_result with action="triage_question" so dispatch
    can post the question blocks.

    Args:
        state: Current AgentState with stage0_gate containing triage context.

    Returns:
        Dict with decision_result containing action, question, and triage_context.
    """
    from src.questions.triage_provider import TriageProvider

    gate_output = state.get("stage0_gate")
    if not gate_output or not gate_output.triage_context:
        logger.warning("triage_questions_node: no triage context found")
        return {"decision_result": {"action": "error", "message": "No triage context"}}

    triage_context = gate_output.triage_context
    provider = TriageProvider()

    question = provider.get_next_question(
        triage_context.gaps,
        {"message": state.get("user_message", "")},
    )

    if not question:
        logger.warning("triage_questions_node: no question generated from gaps")
        return {"decision_result": {"action": "error", "message": "No triage question generated"}}

    logger.info(
        f"triage_questions_node: generated question for gap",
        extra={
            "question_id": question.question_id,
            "question_type": question.question_type.value,
            "target_field": question.target_field,
            "gaps_count": len(triage_context.gaps),
            "completeness_score": triage_context.completeness_score,
        }
    )

    return {
        "decision_result": {
            "action": "triage_question",
            "question": question,
            "triage_context": triage_context,
        }
    }


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
    workflow.add_node("sync_trigger", sync_trigger_node)
    workflow.add_node("jira_search", jira_search_node)
    workflow.add_node("change_request", change_request_node)
    workflow.add_node("ops", ops_node)
    workflow.add_node("draft_transform", draft_transform_node)
    workflow.add_node("task_decomposer", task_decomposer_node)
    workflow.add_node("task_executor", task_executor_node)
    # Terminal response node (Phase 39)
    workflow.add_node("terminal_response", terminal_response_node)
    # Triage questions node (Phase 44)
    workflow.add_node("triage_questions", triage_questions_node)

    # Question collection node - asks LLM for open questions before proceeding
    from src.graph.nodes.question_collection import question_collection_node
    workflow.add_node("question_collection", question_collection_node)

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
            "sync_flow": "sync_trigger",  # Bulk sync with Jira
            "jira_search_flow": "jira_search",  # Search Jira for existing issues
            "change_request_flow": "change_request",  # Diff-based updates (Phase 25.3)
            "ops_flow": "ops",  # Debug failures or explain decisions (Phase 25.2)
            "draft_transform_flow": "draft_transform",  # Structural mutations (Phase 28)
            "task_decomposer_flow": "task_decomposer",  # Multi-intent decomposition (Phase 35)
            "terminal_response_flow": "terminal_response",  # Terminal intents (Phase 39)
            "triage_questions_flow": "triage_questions",  # Triage questions (Phase 44)
            "question_collection_flow": "question_collection",  # Question collection gate
        }
    )

    # Terminal response goes directly to END (Phase 39 - single response then done)
    workflow.add_edge("terminal_response", END)

    # Triage questions goes directly to END (Phase 44 - dispatch posts question)
    workflow.add_edge("triage_questions", END)

    # Question collection goes to END - dispatch handles posting question or proceeding
    workflow.add_edge("question_collection", END)

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

    # Sync trigger goes directly to END after preparing sync summary
    workflow.add_edge("sync_trigger", END)

    # Jira search goes directly to END after preparing search results
    workflow.add_edge("jira_search", END)

    # Change request goes directly to END after preparing diff preview
    workflow.add_edge("change_request", END)

    # OPS goes directly to END after generating debug/explain response
    workflow.add_edge("ops", END)

    # Draft transform goes to END (handler sends structure feedback)
    workflow.add_edge("draft_transform", END)

    # Task decomposer routes to task_executor if tasks exist, else to END
    # Phase 35: Multi-intent decomposition creates TaskPlan, executor processes tasks
    workflow.add_conditional_edges(
        "task_decomposer",
        route_after_decomposer,
        {
            "task_executor": "task_executor",
            "end": END,
        }
    )

    # Task executor processes tasks and returns decision_result to handler
    workflow.add_edge("task_executor", END)

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
    # All five outcomes (ask, preview, ready, preflight, draft_refine) end the graph run
    # The Slack handler will send appropriate response based on decision_result
    workflow.add_conditional_edges(
        "decision",
        route_after_decision,
        {
            "ask": END,  # ASK: questions sent to user
            "preview": END,  # PREVIEW: draft shown for approval
            "ready": END,  # READY: ticket creation (Phase 7)
            "preflight": END,  # PREFLIGHT: EXACT_MATCH found, show blocking duplicate UI
            "draft_refine": END,  # DRAFT_REFINE: user asking about draft structure (Phase 26)
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
