"""Jira integration package."""

from src.jira.client import JiraClient, RateLimitError
from src.jira.models import (
    FieldOwnership,
    FIELD_OWNERSHIP,
    PreflightResult,
    PreflightCheck,
    FieldConflict,
    SyncDiscrepancy,
)

__all__ = [
    # Client
    "JiraClient",
    "RateLimitError",
    # Models
    "FieldOwnership",
    "FIELD_OWNERSHIP",
    "PreflightResult",
    "PreflightCheck",
    "FieldConflict",
    "SyncDiscrepancy",
]
