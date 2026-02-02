"""Domain events with schema versioning for event sourcing.

This module defines the event vocabulary that captures all state changes in the system.
All events are immutable (frozen) Pydantic models with schema versioning support.

Based on spec Part 4: Event Sourcing (maro_2_0.md).
"""

from datetime import datetime
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

# Type aliases for domain identifiers
# These will be replaced with proper types from types.py once 01-02 is executed
ChannelId = str
ThreadTs = str
UserId = str
EntityId = str
JiraKey = str


class DomainEvent(BaseModel):
    """Base for all domain events with schema versioning.

    All domain events are immutable and include:
    - Schema versioning for forward compatibility
    - Correlation/causation IDs for distributed tracing
    - Standard metadata (event_id, timestamp, actor)

    Based on spec 4.1 and RESEARCH.md schema versioning patterns.
    """

    model_config = ConfigDict(frozen=True)

    # From RESEARCH.md - schema versioning from day one
    schema_version: ClassVar[int] = 1

    # From spec 4.1
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    aggregate_id: ChannelId  # Channel is aggregate root
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor_id: UserId
    version: int  # Sequence within aggregate

    # From RESEARCH.md - correlation/causation for tracing
    correlation_id: str | None = None
    causation_id: str | None = None

    @property
    def event_type(self) -> str:
        """Return the event class name as the event type."""
        return self.__class__.__name__

    def model_dump_with_type(self) -> dict[str, Any]:
        """Serialize with event_type and schema_version for storage."""
        data = self.model_dump()
        data["event_type"] = self.event_type
        data["schema_version"] = self.schema_version
        return data


# =============================================================================
# Work Item Events (spec 4.2)
# =============================================================================

# Placeholder for WorkItemContent until 01-02 is executed
# Will be replaced with: from src.domain.content import WorkItemContent
WorkItemContent = dict[str, Any]


class WorkItemDrafted(DomainEvent):
    """Work item draft created in thread.

    Emitted when a user starts drafting a new work item (epic, story, task, bug, spike)
    in a Slack thread.
    """

    entity_id: EntityId
    thread_ts: ThreadTs
    content: WorkItemContent


class WorkItemProposed(DomainEvent):
    """Work item proposed for approval.

    Emitted when a draft work item is posted to the channel for team approval.
    The canonical_message_ts is the Slack message that represents this proposal.
    """

    entity_id: EntityId
    canonical_message_ts: str


class WorkItemApproved(DomainEvent):
    """Work item approved.

    Emitted when a proposed work item receives approval from a team member.
    """

    entity_id: EntityId
    approved_by: UserId


class WorkItemCommitted(DomainEvent):
    """Work item committed to Jira.

    Emitted when an approved work item is projected/synced to Jira.
    """

    entity_id: EntityId
    jira_key: JiraKey


class WorkItemUpdated(DomainEvent):
    """Work item content updated.

    Emitted when a work item's content is modified. The changes dict contains
    the fields that were updated with their new values.
    """

    entity_id: EntityId
    changes: dict[str, Any]
    reason: str


# =============================================================================
# Decision Events (spec 4.2)
# =============================================================================

# Placeholder for DecisionContent until 01-02 is executed
# Will be replaced with: from src.domain.content import DecisionContent
DecisionContent = dict[str, Any]


class DecisionRecorded(DomainEvent):
    """Decision captured from conversation.

    Emitted when an architectural, scope, or process decision is recorded
    from a Slack thread discussion.
    """

    entity_id: EntityId
    thread_ts: ThreadTs
    content: DecisionContent


class DecisionProposed(DomainEvent):
    """Decision proposed for approval.

    Emitted when a recorded decision is posted to the channel for team approval.
    """

    entity_id: EntityId
    canonical_message_ts: str


class DecisionApproved(DomainEvent):
    """Decision approved.

    Emitted when a proposed decision receives approval from a team member.
    """

    entity_id: EntityId
    approved_by: UserId


class DecisionCommitted(DomainEvent):
    """Decision projected to Jira.

    Emitted when an approved decision is synced to Jira, typically as a
    field update on a related issue.
    """

    entity_id: EntityId
    jira_key: JiraKey
    field_path: str


class DecisionDeprecated(DomainEvent):
    """Decision superseded.

    Emitted when a decision is deprecated, typically because a newer
    decision has replaced it.
    """

    entity_id: EntityId
    superseded_by: EntityId | None
    reason: str


# =============================================================================
# Conflict Events (spec 4.2)
# =============================================================================


class ConflictDetected(DomainEvent):
    """Conflict detected between entities or with Jira.

    Emitted when a conflict is detected, such as:
    - Two entities making contradictory decisions
    - An entity conflicting with the current Jira state
    - A sync conflict during projection
    """

    conflict_type: str
    entity_a_id: EntityId
    entity_b_id: EntityId | None  # None for Jira conflicts
    jira_key: JiraKey | None
    description: str


class ConflictResolved(DomainEvent):
    """Conflict resolved.

    Emitted when a detected conflict has been resolved by a team member.
    """

    conflict_id: str
    resolution_type: str
    resolved_by: UserId
    outcome: str
