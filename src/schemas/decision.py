"""Decision entity schema for Phase 30 - First-class decision tracking.

Decisions are versioned entities that represent architectural, scope, constraint,
and process decisions. Jira is a projection of decisions, not the source of truth.

Core shift: From "bot writes to Jira" to "decisions are versioned, Jira is a projection."
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DecisionType(str, Enum):
    """Types of decisions that can be tracked.

    Each type maps to a specific location in Jira tickets.
    See REQUIREMENTS.md R5 for mapping rules.
    """

    ARCH = "arch"  # Architecture decisions -> Description.Architecture section
    SCOPE = "scope"  # Scope/boundary decisions -> Description.Scope section
    CONSTRAINT = "constraint"  # Technical constraints -> Description.Constraints section
    PRIORITY = "priority"  # Priority/ordering decisions -> Priority field
    STRUCTURE = "structure"  # Epic/Story decomposition -> Parent/Link relations
    PROCESS = "process"  # Process/workflow decisions -> Labels or custom field


class DecisionStatus(str, Enum):
    """Lifecycle status of a decision.

    State transitions:
    - PROPOSED: Just suggested, awaiting approval
    - APPROVED: User approved, ready to project to Jira
    - DEPRECATED: No longer active, superseded or abandoned
    - REPLACED: Deprecated with a specific replacement decision
    """

    PROPOSED = "proposed"  # Just suggested, not approved
    APPROVED = "approved"  # Approved by user
    DEPRECATED = "deprecated"  # No longer active
    REPLACED = "replaced"  # Replaced by another decision


class Decision(BaseModel):
    """A first-class decision entity with versioning.

    Decisions are versioned, Jira is a projection.

    Each decision has one canonical message in the channel (pinned),
    with a discussion thread underneath for changes.
    """

    id: str = Field(description="UUID for the decision")
    channel_id: str = Field(description="Slack channel this decision belongs to")
    decision_type: DecisionType = Field(description="Type of decision (ARCH, SCOPE, etc.)")
    title: str = Field(description="Short description of the decision")
    description: str = Field(description="Full explanation of the decision")
    status: DecisionStatus = Field(default=DecisionStatus.PROPOSED)
    version: int = Field(default=1, description="Version number, increments on each change")

    # Provenance
    created_by: str = Field(description="User ID who created the decision")
    created_at: datetime = Field(description="When decision was created")
    updated_at: datetime = Field(description="When decision was last modified")
    approved_by: Optional[str] = Field(default=None, description="User ID who approved")
    approved_at: Optional[datetime] = Field(default=None, description="When approved")

    # For DEPRECATED/REPLACED status
    replaced_by: Optional[str] = Field(
        default=None,
        description="ID of replacement decision (for REPLACED status)",
    )
    deprecation_reason: Optional[str] = Field(
        default=None,
        description="Why this decision was deprecated",
    )

    # Canonical Slack message tracking
    canonical_message_ts: Optional[str] = Field(
        default=None,
        description="Slack message timestamp of the canonical decision message",
    )
    discussion_thread_ts: Optional[str] = Field(
        default=None,
        description="Thread timestamp under the canonical message",
    )


class DecisionVersion(BaseModel):
    """Historical version of a decision.

    When a decision is updated, the previous version is preserved here.
    Enables version history queries and rollback capability.
    """

    id: str = Field(description="UUID for this version record")
    decision_id: str = Field(description="UUID of the parent decision")
    version: int = Field(description="Version number at time of snapshot")
    title: str = Field(description="Title at this version")
    description: str = Field(description="Description at this version")
    status: DecisionStatus = Field(description="Status at this version")
    changed_by: str = Field(description="User ID who made this change")
    changed_at: datetime = Field(description="When this version was created")
    change_reason: Optional[str] = Field(
        default=None,
        description="Why this change was made",
    )


class JiraFieldPath(str, Enum):
    """Standardized Jira field paths for decision projection.

    Decisions map to specific sections/fields in Jira.
    This enables deterministic projection: Decision type -> Jira field.
    No LLM guessing - the mapping is explicit.
    """

    DESC_ARCHITECTURE = "description.architecture"  # ARCH decisions
    DESC_SCOPE = "description.scope"  # SCOPE decisions
    DESC_CONSTRAINTS = "description.constraints"  # CONSTRAINT decisions
    PRIORITY = "priority"  # PRIORITY decisions
    LABELS = "labels"  # PROCESS decisions
    PARENT_LINK = "parent"  # STRUCTURE decisions (epic link)
    CUSTOM_FIELD = "custom_field"  # Extension point


class DecisionLink(BaseModel):
    """Link between a Decision and a Jira ticket field.

    Enables deterministic projection: Decision type -> Jira field.
    Tracks which decisions are linked to which Jira tickets
    and at which version they were last synced.
    """

    id: str = Field(description="UUID for this link")
    decision_id: str = Field(description="UUID of the linked decision")
    jira_key: str = Field(description="Jira issue key (e.g., SCRUM-123)")
    field_path: JiraFieldPath = Field(description="Where in Jira the decision appears")
    linked_at: datetime = Field(description="When this link was established")
    linked_by: str = Field(description="User ID who created the link")
    # Version of decision that was last synced
    synced_version: Optional[int] = Field(
        default=None,
        description="Version of decision that was last synced to this ticket",
    )
    synced_at: Optional[datetime] = Field(
        default=None,
        description="When the decision was last synced to this ticket",
    )


# =============================================================================
# Mapping Rules: Decision type -> default Jira field
# =============================================================================

DECISION_MAPPING_RULES: dict[DecisionType, JiraFieldPath] = {
    DecisionType.ARCH: JiraFieldPath.DESC_ARCHITECTURE,
    DecisionType.SCOPE: JiraFieldPath.DESC_SCOPE,
    DecisionType.CONSTRAINT: JiraFieldPath.DESC_CONSTRAINTS,
    DecisionType.PRIORITY: JiraFieldPath.PRIORITY,
    DecisionType.STRUCTURE: JiraFieldPath.PARENT_LINK,
    DecisionType.PROCESS: JiraFieldPath.LABELS,
}


def get_default_field_path(decision_type: DecisionType) -> JiraFieldPath:
    """Get the default Jira field path for a decision type.

    Each decision type has a deterministic target in Jira.
    No LLM guessing - the mapping is explicit.

    This enforces the deterministic mapping from CONTEXT.md:
    - ARCH -> Description.Architecture section
    - SCOPE -> Description.Scope section
    - CONSTRAINT -> Description.Constraints section
    - PRIORITY -> Priority field
    - STRUCTURE -> Epic/parent link
    - PROCESS -> Labels

    Args:
        decision_type: The type of decision.

    Returns:
        The default JiraFieldPath for that decision type.
    """
    return DECISION_MAPPING_RULES[decision_type]
