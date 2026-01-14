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

__all__ = [
    "JiraService",
    "JiraAPIError",
    "JiraIssueType",
    "JiraPriority",
    "PRIORITY_MAP",
    "JiraIssue",
    "JiraCreateRequest",
]
