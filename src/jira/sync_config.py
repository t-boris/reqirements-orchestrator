"""Field classification and sync configuration for Jira bidirectional sync (Phase 23.4).

Field ownership determines how conflicts are resolved:
- JIRA_OWNED: Jira is source of truth (status, assignee, story points)
- SLACK_OWNED: Slack is source of truth (description sections, decisions, constraints)
- SHARED: Both can edit, requires conflict detection (priority, due date, dependencies)

Philosophy: Slack captures the "why", Jira manages the "what/who/when".
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FieldOwnership(str, Enum):
    """Ownership classification for sync fields."""

    JIRA_OWNED = "jira_owned"  # Jira is source of truth, Slack can suggest but not push
    SLACK_OWNED = "slack_owned"  # Slack is source of truth, Jira receives updates
    SHARED = "shared"  # Both can edit, conflict detection required


class SyncField(BaseModel):
    """Configuration for a syncable field."""

    name: str = Field(description="Field name (e.g., 'summary', 'status')")
    ownership: FieldOwnership = Field(description="Who owns this field")
    jira_field: str = Field(description="Jira API field name")
    allow_suggest: bool = Field(
        default=True,
        description="For JIRA_OWNED: can Slack suggest changes?",
    )


# Field classification based on 23-CONTEXT.md
# Jira-owned: status, assignee, story points (Slack can suggest, not push)
# Slack-owned: description sections, links, decisions/constraints
# Shared: priority, due date, dependencies (conflict-detect)

FIELD_CLASSIFICATIONS: dict[str, SyncField] = {
    # Jira-owned fields - Jira is the execution system
    "status": SyncField(
        name="status",
        ownership=FieldOwnership.JIRA_OWNED,
        jira_field="status",
        allow_suggest=True,  # Can suggest status transitions
    ),
    "assignee": SyncField(
        name="assignee",
        ownership=FieldOwnership.JIRA_OWNED,
        jira_field="assignee",
        allow_suggest=True,  # Can suggest assignments
    ),
    "story_points": SyncField(
        name="story_points",
        ownership=FieldOwnership.JIRA_OWNED,
        jira_field="customfield_10016",  # Common story points field
        allow_suggest=True,
    ),
    "sprint": SyncField(
        name="sprint",
        ownership=FieldOwnership.JIRA_OWNED,
        jira_field="customfield_10020",  # Common sprint field
        allow_suggest=False,  # Sprint assignment is pure Jira
    ),
    # Slack-owned fields - Communication is source of truth
    "summary": SyncField(
        name="summary",
        ownership=FieldOwnership.SLACK_OWNED,
        jira_field="summary",
    ),
    "description": SyncField(
        name="description",
        ownership=FieldOwnership.SLACK_OWNED,
        jira_field="description",
    ),
    "labels": SyncField(
        name="labels",
        ownership=FieldOwnership.SLACK_OWNED,
        jira_field="labels",
    ),
    # Shared fields - Require conflict detection
    "priority": SyncField(
        name="priority",
        ownership=FieldOwnership.SHARED,
        jira_field="priority",
    ),
    "due_date": SyncField(
        name="due_date",
        ownership=FieldOwnership.SHARED,
        jira_field="duedate",
    ),
}


class SyncDirection(str, Enum):
    """Direction of sync operation."""

    SLACK_TO_JIRA = "slack_to_jira"  # Push from Slack to Jira
    JIRA_TO_SLACK = "jira_to_slack"  # Pull from Jira to Slack
    BIDIRECTIONAL = "bidirectional"  # Check both directions


class SyncResult(BaseModel):
    """Result of a sync operation."""

    success: bool = Field(description="Whether sync completed successfully")
    direction: SyncDirection = Field(description="Direction of sync")
    fields_updated: list[str] = Field(
        default_factory=list, description="Fields that were updated"
    )
    conflicts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Conflicts requiring manual resolution",
    )
    error: str | None = Field(default=None, description="Error message if failed")


def can_push_field(field_name: str, direction: SyncDirection) -> bool:
    """Check if a field can be pushed in the given direction.

    Args:
        field_name: Name of the field
        direction: Sync direction

    Returns:
        True if field can be pushed in this direction
    """
    field = FIELD_CLASSIFICATIONS.get(field_name)
    if not field:
        return False

    if direction == SyncDirection.SLACK_TO_JIRA:
        # Can only push SLACK_OWNED and SHARED fields
        return field.ownership in (FieldOwnership.SLACK_OWNED, FieldOwnership.SHARED)

    elif direction == SyncDirection.JIRA_TO_SLACK:
        # Can only pull JIRA_OWNED and SHARED fields
        return field.ownership in (FieldOwnership.JIRA_OWNED, FieldOwnership.SHARED)

    return False


def requires_conflict_check(field_name: str) -> bool:
    """Check if a field requires conflict detection on sync.

    Args:
        field_name: Name of the field

    Returns:
        True if field is SHARED and needs conflict check
    """
    field = FIELD_CLASSIFICATIONS.get(field_name)
    return field is not None and field.ownership == FieldOwnership.SHARED
