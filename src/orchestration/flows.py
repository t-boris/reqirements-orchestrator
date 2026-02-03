"""Flow templates for task-based orchestration.

FlowTemplates guide (not enforce) task execution by suggesting what context
to gather. Unlike rigid stage machines, they allow flexible, non-linear
conversations where users can revisit earlier context as needed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowTemplate:
    """Template that guides (not enforces) task execution.

    Unlike rigid stage machines, FlowTemplates suggest what context to gather
    but don't enforce order. Tasks can gather context in any order and revisit
    as needed.
    """

    flow_type: str
    description: str
    suggested_context: tuple[str, ...]  # What we'd like to know (order is hint)
    required_context: tuple[str, ...]  # Minimum to complete
    allows_cycles: bool = True  # Can revisit earlier context
    allows_fan_out: bool = False  # Can spawn child tasks
    child_flow: str | None = None  # Flow type for children (if fan_out)
    entity_type: str | None = None  # Type of entity this creates (work_item, decision)


# =============================================================================
# Predefined Flow Templates
# =============================================================================

CREATE_WORK_ITEM = FlowTemplate(
    flow_type="create_work_item",
    description="Create a single work item (epic, story, task, bug, spike)",
    suggested_context=("what", "why", "acceptance_criteria", "priority", "estimate"),
    required_context=("what",),  # Minimum: know what to build
    entity_type="work_item",
)

CREATE_DECISION = FlowTemplate(
    flow_type="create_decision",
    description="Capture an architectural or process decision",
    suggested_context=("decision", "rationale", "alternatives", "consequences", "scope"),
    required_context=("decision",),  # Minimum: the decision itself
    entity_type="decision",
)

ARCHITECTURE_REVIEW = FlowTemplate(
    flow_type="architecture_review",
    description="Multi-entity architecture discussion",
    suggested_context=("goal", "scope", "constraints", "components", "risks"),
    required_context=("goal",),  # Minimum: know what we're reviewing
    allows_fan_out=True,  # Can spawn decision/work_item tasks
)

BATCH_CREATE = FlowTemplate(
    flow_type="batch_create",
    description="Create multiple items in parallel (e.g., stories for each epic)",
    suggested_context=("targets", "template", "common_context"),
    required_context=("targets",),  # Minimum: list of things to create
    allows_fan_out=True,
    child_flow="create_work_item",
)

REVIEW = FlowTemplate(
    flow_type="review",
    description="Review and refine existing entities",
    suggested_context=("entities", "feedback", "changes"),
    required_context=("entities",),  # Minimum: what to review
    allows_cycles=True,
)

CONVERSE = FlowTemplate(
    flow_type="converse",
    description="Free-form conversation without specific goal",
    suggested_context=(),  # No specific context needed
    required_context=(),  # Can complete anytime
    allows_cycles=True,
)


# Registry for lookup by flow_type
FLOW_TEMPLATES: dict[str, FlowTemplate] = {
    "create_work_item": CREATE_WORK_ITEM,
    "create_decision": CREATE_DECISION,
    "architecture_review": ARCHITECTURE_REVIEW,
    "batch_create": BATCH_CREATE,
    "review": REVIEW,
    "converse": CONVERSE,
}


def get_flow_template(flow_type: str) -> FlowTemplate:
    """Get flow template by type, defaulting to CONVERSE for unknown types."""
    return FLOW_TEMPLATES.get(flow_type, CONVERSE)


def can_complete(context: dict, flow: FlowTemplate) -> bool:
    """Check if task has minimum required context to complete."""
    return all(key in context and context[key] for key in flow.required_context)


def missing_context(context: dict, flow: FlowTemplate) -> list[str]:
    """Get list of required context keys still missing."""
    return [key for key in flow.required_context if key not in context or not context[key]]


def suggested_next(context: dict, flow: FlowTemplate) -> list[str]:
    """Get suggested context keys to gather next (not required, but helpful)."""
    return [key for key in flow.suggested_context if key not in context]
