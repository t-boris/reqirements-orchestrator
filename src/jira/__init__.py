"""Jira integration package.

Provides JiraService for creating and searching Jira issues,
along with type definitions for Jira operations.
"""
from src.jira.types import (
    JiraIssueType,
    JiraPriority,
    PRIORITY_MAP,
    JiraIssue,
    JiraCreateRequest,
)
from src.jira.client import JiraService, JiraAPIError
from src.jira.sync_config import (
    FieldOwnership,
    SyncField,
    SyncDirection,
    SyncResult,
    FIELD_CLASSIFICATIONS,
    can_push_field,
    requires_conflict_check,
)
from src.jira.sync_service import JiraSyncService

__all__ = [
    "JiraService",
    "JiraAPIError",
    "JiraIssueType",
    "JiraPriority",
    "PRIORITY_MAP",
    "JiraIssue",
    "JiraCreateRequest",
    "FieldOwnership",
    "SyncField",
    "SyncDirection",
    "SyncResult",
    "FIELD_CLASSIFICATIONS",
    "can_push_field",
    "requires_conflict_check",
    "JiraSyncService",
]
