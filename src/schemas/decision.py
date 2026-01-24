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
