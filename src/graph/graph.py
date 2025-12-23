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
from src.graph.routers import (
    should_respond_router,
    intent_router,
    critique_router,
    human_decision_router,
    conflict_router,
    discovery_router,
    intake_router,
    architecture_router,
    scope_router,
    story_router,
    task_router,
    estimation_router,
    security_router,
    validation_router,
    final_review_router,
    impact_router,
)
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
    on_node_start: callable = None,
    on_node_end: callable = None,
) -> RequirementState:
    """
    Invoke the graph with initial state, with optional progress callbacks.

    This is the main entry point for processing messages.

    Args:
        initial_state: Initial state with message and context.
        thread_id: Unique thread ID for state persistence (channel_id + thread_ts).
        on_node_start: Optional async callback(node_name) when node starts.
        on_node_end: Optional async callback(node_name, state) when node ends.

    Returns:
        Final state after graph execution.
    """
    graph = await get_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    # If no callbacks, use simple invoke
    if not on_node_start and not on_node_end:
        result = await graph.ainvoke(initial_state, config=config)
        return result

    # Use streaming to get node-by-node progress
    result = dict(initial_state)
    async for event in graph.astream(initial_state, config=config, stream_mode="updates"):
        # event is dict like {"node_name": state_update}
        for node_name, state_update in event.items():
            if on_node_start:
                await on_node_start(node_name)

            # Track final state (state_update can be None if node returns nothing)
            if state_update:
                result.update(state_update)

            if on_node_end:
                await on_node_end(node_name, result)

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
