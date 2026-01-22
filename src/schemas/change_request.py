"""Change request schemas for diff-based updates."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel


class ChangeTargetType(str, Enum):
    """Type of entity being changed."""
    WORKITEM = "workitem"
    JIRA_ISSUE = "jira_issue"
    DECISION = "decision"
    ARTIFACT = "artifact"


class ChangeOperation(str, Enum):
    """Type of change operation."""
    UPDATE = "update"      # Modify fields
    DELETE = "delete"      # Remove entity
    SPLIT = "split"        # Split into multiple
    MERGE = "merge"        # Merge multiple into one
    MOVE = "move"          # Change parent/epic
    LINK = "link"          # Add relationship


class FieldChange(BaseModel):
    """Single field change in a diff."""
    field: str
    old_value: Any
    new_value: Any


class ChangeTarget(BaseModel):
    """Target of a change request."""
    target_type: ChangeTargetType
    target_id: str  # workitem_id, jira_key, commit_id
    target_summary: Optional[str] = None


class ChangeRequest(BaseModel):
    """A request to change existing truth."""
    request_id: str
    channel_id: str
    thread_ts: str
    requester_id: str
    operation: ChangeOperation
    targets: list[ChangeTarget]
    changes: list[FieldChange]
    reason: Optional[str] = None
    created_at: datetime
    status: str = "pending"  # pending, approved, rejected, applied


class ChangePreview(BaseModel):
    """Preview of changes for user approval."""
    request: ChangeRequest
    affected_items: list[dict]  # Current state of targets
    preview_text: str  # Human-readable diff
    warnings: list[str] = []
    requires_jira_sync: bool = False
