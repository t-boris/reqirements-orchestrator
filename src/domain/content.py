"""Content types for entities.

Part 3.4-3.7, 3.9 of MARO 2.0 spec: WorkItemContent, DecisionContent,
Attribution, Modification, JiraLink, Approval, Objection.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .types import EntityId, JiraKey, SyncStatus, UserId, Version


# === Issue Type Enum (Spec 3.4) ===

class IssueType(str, Enum):
    """Type of work item."""
    EPIC = "epic"
    STORY = "story"
    TASK = "task"
    BUG = "bug"
    SPIKE = "spike"


# === Work Item Content (Spec 3.4) ===

class WorkItemContent(BaseModel):
    """Content for work items."""
    model_config = ConfigDict(frozen=True)

    issue_type: IssueType
    title: str
    description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    # Hierarchy
    parent_id: EntityId | None = None
    children_ids: list[EntityId] = Field(default_factory=list)

    def validate_content(self) -> list[str]:
        """Return validation errors."""
        errors = []
        if not self.title:
            errors.append("Title is required")
        if self.issue_type == IssueType.STORY and not self.acceptance_criteria:
            errors.append("Stories require acceptance criteria")
        if self.issue_type == IssueType.EPIC and not self.description:
            errors.append("Epics require a description/goal")
        return errors


# === Decision Type Enum (Spec 3.5) ===

class DecisionType(str, Enum):
    """Type of decision."""
    ARCHITECTURE = "architecture"   # Technical design choices
    SCOPE = "scope"                 # What's in/out
    CONSTRAINT = "constraint"       # Non-negotiable requirements
    PRIORITY = "priority"           # Ordering decisions
    PROCESS = "process"             # How we work
    STRUCTURE = "structure"         # Epic/story breakdown


# === Decision Content (Spec 3.5) ===

class DecisionContent(BaseModel):
    """Content for decisions."""
    model_config = ConfigDict(frozen=True)

    decision_type: DecisionType
    title: str
    description: str
    rationale: str = ""
    alternatives_considered: list[str] = Field(default_factory=list)

    # Links to affected entities
    affects_entities: list[EntityId] = Field(default_factory=list)


# === Attribution (Spec 3.6) ===

class Modification(BaseModel):
    """Record of a change."""
    model_config = ConfigDict(frozen=True)

    user_id: UserId
    action: str
    timestamp: datetime
    description: str


class Attribution(BaseModel):
    """Who did what and when."""
    model_config = ConfigDict(frozen=True)

    proposed_by: UserId
    proposed_at: datetime
    approved_by: UserId | None = None
    approved_at: datetime | None = None
    modifications: list[Modification] = Field(default_factory=list)


# === Jira Link (Spec 3.7) ===

class JiraLink(BaseModel):
    """Link between entity and Jira issue."""
    model_config = ConfigDict(frozen=True)

    jira_key: JiraKey
    synced_version: Version
    synced_at: datetime
    sync_status: SyncStatus

    # For decisions: which field this decision affects
    field_path: str | None = None  # e.g., "description", "customfield_10001"


# === Approval & Objection (Spec 3.9) ===

class Approval(BaseModel):
    """Approval record."""
    model_config = ConfigDict(frozen=True)

    user_id: UserId
    timestamp: datetime
    comment: str | None = None


class ObjectionStatus(str, Enum):
    """Status of an objection."""
    ACTIVE = "active"
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"


class Objection(BaseModel):
    """Objection that blocks approval."""
    model_config = ConfigDict(frozen=True)

    user_id: UserId
    timestamp: datetime
    reason: str
    status: ObjectionStatus = ObjectionStatus.ACTIVE
    resolution: str | None = None
