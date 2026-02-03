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
from src.jira.preflight import PreflightService
from src.jira.sync_service import (
    JiraSyncService,
    JiraSyncError,
    DuplicateDetectedError,
    ConflictDetectedError,
)
from src.jira.commit_handler import (
    CommitHandler,
    CommitResult,
    CommitStatus,
)
from src.jira.reconciliation import (
    ReconciliationService,
    ReconciliationReport,
    ResolutionChoice,
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
    # Services
    "PreflightService",
    "JiraSyncService",
    "JiraSyncError",
    "DuplicateDetectedError",
    "ConflictDetectedError",
    # Handler
    "CommitHandler",
    "CommitResult",
    "CommitStatus",
    # Reconciliation
    "ReconciliationService",
    "ReconciliationReport",
    "ResolutionChoice",
]
