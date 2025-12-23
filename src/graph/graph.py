"""
LangGraph Graph Definition - Composes nodes into the requirements workflow.

This module defines the state graph with all nodes, edges, and conditional routing.
The graph implements the reflexion pattern with human-in-the-loop approval.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from src.config.settings import get_settings
from src.graph.nodes import (
    architecture_exploration_node,
    conflict_detection_node,
    critique_node,
    discovery_node,
    draft_node,
    estimation_node,
    final_review_node,
    human_approval_node,
    impact_analysis_node,
    intake_node,
    intent_classifier_node,
    jira_add_node,
    jira_delete_node,
    jira_read_node,
    jira_status_node,
    jira_update_node,
    jira_write_node,
    memory_node,
    memory_update_node,
    no_response_node,
    process_human_decision_node,
    response_node,
    scope_definition_node,
    security_review_node,
    story_breakdown_node,
    task_breakdown_node,
    validation_node,
)
from src.graph.state import HumanDecision, IntentType, RequirementState, WorkflowPhase

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


def discovery_router(state: RequirementState) -> str:
    """
    Route after discovery based on whether we have enough info.

    Returns:
        "respond" if we have questions to ask, "draft" if ready to proceed.
    """
    # If discovery node set a response (questions to ask), go to response
    if state.get("response") and state.get("should_respond"):
        return "respond"

    # Otherwise proceed to drafting
    return "draft"


def intake_router(state: RequirementState) -> str:
    """
    Route after intake based on intent and context sufficiency.

    Returns:
        Node name to route to.
    """
    if not state.get("should_respond", False):
        return "no_response"

    intent = state.get("intent")

    # Jira command intents (CRUD)
    if intent == IntentType.JIRA_SYNC.value:
        return "jira_write"
    if intent == IntentType.JIRA_READ.value:
        return "jira_read"
    if intent == IntentType.JIRA_STATUS.value:
        return "jira_status"
    if intent == IntentType.JIRA_ADD.value:
        return "jira_add"
    if intent == IntentType.JIRA_UPDATE.value:
        return "jira_update"
    if intent == IntentType.JIRA_DELETE.value:
        return "jira_delete"

    # Modification intent - needs impact analysis
    if intent == IntentType.MODIFICATION.value:
        return "impact_analysis"

    # Non-requirement intents go directly to response
    if intent != IntentType.REQUIREMENT.value:
        return "response"

    # Requirements: check if we need discovery
    clarifying_questions = state.get("clarifying_questions", [])
    if clarifying_questions:
        return "discovery"

    # Enough context, go to architecture exploration
    return "architecture"


def architecture_router(state: RequirementState) -> str:
    """
    Route after architecture options are presented.

    Returns:
        "respond" to show options, "scope" if architecture already chosen.
    """
    # If we have a response ready (architecture options), show it
    if state.get("response") and state.get("should_respond"):
        return "respond"

    # If architecture already chosen, proceed to scope
    if state.get("chosen_architecture"):
        return "scope"

    # Default: show options
    return "respond"


def scope_router(state: RequirementState) -> str:
    """
    Route after scope is defined.

    Returns:
        "respond" to show scope for confirmation, "stories" to proceed.
    """
    # If we have a response ready (scope), show it
    if state.get("response") and state.get("should_respond"):
        return "respond"

    # If scope is confirmed (epics defined), proceed to stories
    if state.get("epics"):
        return "stories"

    return "respond"


def story_router(state: RequirementState) -> str:
    """
    Route after stories are generated.

    Returns:
        "respond" to show stories, "tasks" to proceed.
    """
    # If we have a response ready (stories), show it
    if state.get("response") and state.get("should_respond"):
        return "respond"

    # If stories are confirmed, proceed to tasks
    if state.get("stories"):
        return "tasks"

    return "respond"


def task_router(state: RequirementState) -> str:
    """
    Route after tasks are generated.

    Returns:
        "respond" to show tasks, "estimation" to proceed to estimation.
    """
    # If we have a response ready (tasks), show it
    if state.get("response") and state.get("should_respond"):
        return "respond"

    # If tasks are confirmed, proceed to estimation
    if state.get("tasks"):
        return "estimation"

    return "respond"


def estimation_router(state: RequirementState) -> str:
    """
    Route after estimation is complete.

    Returns:
        "respond" to show estimation, "security" to proceed to security review.
    """
    # If we have a response ready (estimation), show it
    if state.get("response") and state.get("should_respond"):
        return "respond"

    # If estimation is confirmed, proceed to security review
    if state.get("total_story_points") is not None:
        return "security"

    return "respond"


def security_router(state: RequirementState) -> str:
    """
    Route after security review is complete.

    Returns:
        "respond" to show review, "validation" to proceed.
    """
    # If we have a response ready, show it
    if state.get("response") and state.get("should_respond"):
        return "respond"

    # If security phase complete, proceed to validation
    current_phase = state.get("current_phase")
    if current_phase == WorkflowPhase.SECURITY.value:
        return "validation"

    return "respond"


def validation_router(state: RequirementState) -> str:
    """
    Route after validation is complete.

    Returns:
        "respond" to show validation, "final_review" to proceed.
    """
    # If we have a response ready, show it
    if state.get("response") and state.get("should_respond"):
        return "respond"

    # If validation complete, proceed to final review
    if state.get("validation_report"):
        return "final_review"

    return "respond"


def final_review_router(state: RequirementState) -> str:
    """
    Route after final review - goes to human approval.

    Returns:
        "human_approval" to await user decision.
    """
    # Final review always goes to human approval
    return "human_approval"


def impact_router(state: RequirementState) -> str:
    """
    Route after impact analysis based on restart_phase.

    Routes to the appropriate phase to begin re-evaluation,
    or to response if it's a text-only change.

    Returns:
        Phase node to restart from, or "response" for text-only changes.
    """
    restart_phase = state.get("restart_phase")

    if not restart_phase:
        # Text-only or no re-evaluation needed
        return "response"

    # Map phases to node names
    phase_to_node = {
        WorkflowPhase.ARCHITECTURE.value: "architecture",
        WorkflowPhase.SCOPE.value: "scope",
        WorkflowPhase.STORIES.value: "stories",
        WorkflowPhase.TASKS.value: "tasks",
        WorkflowPhase.ESTIMATION.value: "estimation",
    }

    node = phase_to_node.get(restart_phase)
    if node:
        return node

    # Default to response if unknown phase
    return "response"


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
    builder.add_node("intake", intake_node)  # Phase 1: Enhanced intake
    builder.add_node("discovery", discovery_node)  # Phase 2: Clarifying questions
    builder.add_node("architecture", architecture_exploration_node)  # Phase 3: Architecture options
    builder.add_node("scope", scope_definition_node)  # Phase 4: Scope definition
    builder.add_node("stories", story_breakdown_node)  # Phase 5: Story breakdown
    builder.add_node("tasks", task_breakdown_node)  # Phase 6: Task breakdown
    builder.add_node("estimation", estimation_node)  # Phase 7: Estimation
    builder.add_node("security", security_review_node)  # Phase 8: Security review
    builder.add_node("validation", validation_node)  # Phase 9: Validation
    builder.add_node("final_review", final_review_node)  # Phase 10: Final review
    builder.add_node("human_approval", human_approval_node)  # Human approval
    builder.add_node("process_decision", process_human_decision_node)
    builder.add_node("jira_write", jira_write_node)  # Phase 11: Jira sync
    builder.add_node("jira_read", jira_read_node)  # Re-read Jira issue
    builder.add_node("jira_status", jira_status_node)  # Show thread status
    builder.add_node("jira_add", jira_add_node)  # Add story/task to epic
    builder.add_node("jira_update", jira_update_node)  # Update Jira issue
    builder.add_node("jira_delete", jira_delete_node)  # Delete Jira issue
    builder.add_node("impact_analysis", impact_analysis_node)  # Impact analysis for modifications
    builder.add_node("memory_update", memory_update_node)
    builder.add_node("response", response_node)
    builder.add_node("no_response", no_response_node)

    # Set entry point
    builder.set_entry_point("memory")

    # Memory -> Intake (replaces intent_classifier)
    builder.add_edge("memory", "intake")

    # Intake -> Conditional routing based on intent and context sufficiency
    builder.add_conditional_edges(
        "intake",
        intake_router,
        {
            "discovery": "discovery",  # Needs clarifying questions
            "architecture": "architecture",  # Go to architecture exploration
            "impact_analysis": "impact_analysis",  # Modification - analyze impact first
            "jira_write": "jira_write",  # Jira sync/create request
            "jira_read": "jira_read",  # Re-read Jira issue
            "jira_status": "jira_status",  # Show thread status
            "jira_add": "jira_add",  # Add story/task to epic
            "jira_update": "jira_update",  # Update Jira issue
            "jira_delete": "jira_delete",  # Delete Jira issue
            "response": "response",  # Questions, general, off-topic
            "no_response": "no_response",  # Below confidence threshold
        },
    )

    # Discovery -> Conditional routing based on whether we have questions
    builder.add_conditional_edges(
        "discovery",
        discovery_router,
        {
            "respond": "response",  # Ask clarifying questions
            "draft": "architecture",  # Have enough info, proceed to architecture
        },
    )

    # Architecture -> Conditional routing (show options or proceed to scope)
    builder.add_conditional_edges(
        "architecture",
        architecture_router,
        {
            "respond": "response",  # Show architecture options
            "scope": "scope",  # Architecture chosen, proceed to scope
        },
    )

    # Scope -> Conditional routing (show scope or proceed to stories)
    builder.add_conditional_edges(
        "scope",
        scope_router,
        {
            "respond": "response",  # Show scope for confirmation
            "stories": "stories",  # Scope confirmed, proceed to stories
        },
    )

    # Stories -> Conditional routing (show stories or proceed to tasks)
    builder.add_conditional_edges(
        "stories",
        story_router,
        {
            "respond": "response",  # Show stories for confirmation
            "tasks": "tasks",  # Stories confirmed, proceed to tasks
        },
    )

    # Tasks -> Conditional routing (show tasks or proceed to estimation)
    builder.add_conditional_edges(
        "tasks",
        task_router,
        {
            "respond": "response",  # Show tasks for confirmation
            "estimation": "estimation",  # Tasks confirmed, proceed to estimation
        },
    )

    # Estimation -> Conditional routing (show estimation or proceed to security)
    builder.add_conditional_edges(
        "estimation",
        estimation_router,
        {
            "respond": "response",  # Show estimation for confirmation
            "security": "security",  # Estimation confirmed, proceed to security
        },
    )

    # Security -> Conditional routing (show review or proceed to validation)
    builder.add_conditional_edges(
        "security",
        security_router,
        {
            "respond": "response",  # Show security review
            "validation": "validation",  # Proceed to validation
        },
    )

    # Validation -> Conditional routing (show validation or proceed to final review)
    builder.add_conditional_edges(
        "validation",
        validation_router,
        {
            "respond": "response",  # Show validation report
            "final_review": "final_review",  # Proceed to final review
        },
    )

    # Final Review -> Human Approval (interrupt point)
    builder.add_edge("final_review", "human_approval")

    # Human Approval is an interrupt point
    # After human makes decision, process it
    builder.add_edge("human_approval", "process_decision")

    # Process Decision -> Conditional routing
    builder.add_conditional_edges(
        "process_decision",
        human_decision_router,
        {
            "write_jira": "jira_write",
            "edit": "discovery",  # Back to discovery to refine requirements
            "reject": "response",  # Respond with rejection message
            "pending": END,  # Edge case - shouldn't happen
        },
    )

    # Jira Write -> Memory Update
    builder.add_edge("jira_write", "memory_update")

    # Jira Command nodes -> Response (they set their own response)
    builder.add_edge("jira_read", "response")
    builder.add_edge("jira_status", "response")
    builder.add_edge("jira_add", "response")
    builder.add_edge("jira_update", "response")
    builder.add_edge("jira_delete", "response")

    # Impact Analysis -> Route to appropriate phase or response
    builder.add_conditional_edges(
        "impact_analysis",
        impact_router,
        {
            "architecture": "architecture",  # Re-evaluate from architecture
            "scope": "scope",  # Re-evaluate from scope
            "stories": "stories",  # Re-evaluate from stories
            "tasks": "tasks",  # Re-evaluate from tasks
            "estimation": "estimation",  # Re-evaluate estimation only
            "response": "response",  # Text-only change, just respond
        },
    )

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
