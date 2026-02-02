"""Unified entity sum types.

Part 3.8 of MARO 2.0 spec: Entity sum type pattern - makes illegal states unrepresentable.

Each entity variant represents a specific lifecycle state:
- DraftEntity: Being formed in thread, no Jira link possible
- ProposedEntity: Visible in channel, awaiting approval
- ApprovedEntity: Approved, ready for Jira projection
- CommittedEntity: Projected to Jira, has required JiraLink
- DeprecatedEntity: Superseded (decisions only)
"""

from datetime import datetime
from typing import Union

from pydantic import BaseModel, ConfigDict, Field

from .content import (
    Approval,
    Attribution,
    DecisionContent,
    JiraLink,
    Objection,
    WorkItemContent,
)
from .types import (
    ChannelId,
    EntityId,
    EntityLifecycle,
    EntityType,
    ThreadTs,
    Version,
)


# === Entity Content Union ===

EntityContent = Union[WorkItemContent, DecisionContent]


# === Entity Sum Types (Spec 3.8) ===

class DraftEntity(BaseModel):
    """Entity being formed - no Jira link possible."""
    model_config = ConfigDict(frozen=True)

    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    thread_ts: ThreadTs
    content: EntityContent
    attribution: Attribution
    version: Version = Version(1)


class ProposedEntity(BaseModel):
    """Entity proposed for approval - has canonical message."""
    model_config = ConfigDict(frozen=True)

    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    thread_ts: ThreadTs
    content: EntityContent
    attribution: Attribution
    version: Version
    canonical_message_ts: str
    approvals: list[Approval] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)


class ApprovedEntity(BaseModel):
    """Entity approved - ready for Jira projection."""
    model_config = ConfigDict(frozen=True)

    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    thread_ts: ThreadTs
    content: EntityContent
    attribution: Attribution  # Now has approved_by
    version: Version
    canonical_message_ts: str


class CommittedEntity(BaseModel):
    """Entity committed to Jira - has required JiraLink."""
    model_config = ConfigDict(frozen=True)

    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    thread_ts: ThreadTs
    content: EntityContent
    attribution: Attribution
    version: Version
    canonical_message_ts: str
    jira_link: JiraLink  # Required, not optional!


class DeprecatedEntity(BaseModel):
    """Entity superseded - for decisions only."""
    model_config = ConfigDict(frozen=True)

    id: EntityId
    entity_type: EntityType
    channel_id: ChannelId
    content: EntityContent
    attribution: Attribution
    version: Version
    canonical_message_ts: str
    jira_link: JiraLink | None = None
    deprecated_at: datetime
    superseded_by: EntityId | None = None


# === The Union Type ===
# Entity can only be in ONE state - this is the sum type pattern

Entity = Union[DraftEntity, ProposedEntity, ApprovedEntity, CommittedEntity, DeprecatedEntity]


# === Lifecycle Helper ===

def get_lifecycle(entity: Entity) -> EntityLifecycle:
    """Get lifecycle from entity type.

    Uses structural matching to determine lifecycle from entity class.
    """
    match entity:
        case DraftEntity():
            return EntityLifecycle.DRAFT
        case ProposedEntity():
            return EntityLifecycle.PROPOSED
        case ApprovedEntity():
            return EntityLifecycle.APPROVED
        case CommittedEntity():
            return EntityLifecycle.COMMITTED
        case DeprecatedEntity():
            return EntityLifecycle.DEPRECATED
        case _:
            raise ValueError(f"Unknown entity type: {type(entity)}")
