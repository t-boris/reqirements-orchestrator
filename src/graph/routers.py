"""
Graph routing functions.

Conditional edge routers for the LangGraph workflow.
"""

import structlog

from src.graph.state import (
    HumanDecision,
    RequirementState,
    WorkflowPhase,
)

logger = structlog.get_logger()

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

    # Proceed intent - skip discovery and go directly to architecture
    if intent == IntentType.PROCEED.value:
        return "architecture"

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