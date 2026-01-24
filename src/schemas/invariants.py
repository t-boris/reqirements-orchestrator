"""Invariant violation types for Phase 32 - Product Invariants.

ARCHITECTURE:
Invariants are enforced at multiple layers:
- Layer 0: Types (this file) - make wrong path hard
- Layer 1: Boundaries (gateways) - one door, one key
- Layer 2: Tokens (PreflightToken, etc.) - prove checks passed
- Layer 3: CI gates - make wrong path unshippable
- Layer 4: Runtime guardrails - make failures survivable

These exceptions bubble up - NEVER catch and swallow.
Catching is allowed only in:
- Test assertions
- Override handlers (with OverrideToken)
- Top-level error handlers (for logging)
"""
from typing import Any, Never


class InvariantViolation(Exception):
    """Base class for invariant violations.

    INVARIANT: These exceptions must never be caught and swallowed in normal code paths.
    They represent fundamental system guarantees being violated.

    If you're tempted to catch one of these, you need either:
    1. An OverrideToken (emergency bypass with audit)
    2. A fix for the underlying code that violated the invariant
    """

    invariant_name: str = "UNKNOWN"

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        """Initialize with message and optional context.

        Args:
            message: Human-readable description of the violation.
            context: Additional context (operation, entity IDs, etc.)
        """
        super().__init__(message)
        self.context = context or {}


class ManagedSectionViolation(InvariantViolation):
    """Attempted to modify Jira description outside managed section.

    INVARIANT: I4 - MANAGED_SECTION = Law
    MARO writes only to clearly marked sections.
    Hand-written content above/below is never touched.

    This violation means code attempted to:
    - Write to Jira description without going through managed_sections.py
    - Modify content outside the ## Decisions (managed by MARO) section
    """

    invariant_name = "MANAGED_SECTION_ONLY"


class PreflightRequired(InvariantViolation):
    """Attempted Jira write without preflight check.

    INVARIANT: All Jira writes must pass preflight to detect conflicts.

    This violation means code attempted to:
    - Call Jira create/update API without acquiring PreflightToken
    - Bypass conflict detection (IDEMPOTENT, SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL)

    Preflight ensures:
    - No accidental overwrites of external changes
    - User confirms resolution strategy for conflicts
    - Audit trail of conflict resolutions
    """

    invariant_name = "PREFLIGHT_REQUIRED"


class SlackWriteFromHandler(InvariantViolation):
    """Slack handler attempted to write to truth store directly.

    INVARIANT: I2 - Slack = UI (handlers read-only, mutations via graph)

    Architecture:
    - TRUTH LAYER: DecisionStore, WorkItemStore, DraftStore
      - ONLY graph nodes can write
    - PROJECTION LAYER: JiraSyncService, DecisionSyncService
      - Writes to Jira based on registry state
    - PRESENTATION LAYER: Slack handlers, managers, block builders
      - Read-only access to registries
      - Can trigger graph actions via dispatch

    This violation means a Slack handler attempted to:
    - Call store.create(), store.update(), store.delete() directly
    - Bypass the graph dispatch mechanism
    """

    invariant_name = "SLACK_IS_UI"


class CommitLogMutation(InvariantViolation):
    """Attempted to modify or delete commit log entry.

    INVARIANT: I3 - Commit Log = Append-Only

    The commit log is event-sourced:
    - Entries are NEVER modified after creation
    - Entries are NEVER deleted
    - Canonical messages can be rebuilt from log at any time
    - On conflict, commit log wins

    This violation means code attempted to:
    - Update an existing commit log entry
    - Delete a commit log entry
    - Modify fields on a frozen CommitLogEntry instance
    """

    invariant_name = "COMMIT_LOG_APPEND_ONLY"


def raise_invariant_violation(
    violation_type: type[InvariantViolation],
    operation: str,
    context: dict[str, Any],
) -> Never:
    """Raise invariant violation with structured context.

    NEVER catch these in normal code paths.
    Catching is allowed only in:
    - Test assertions
    - Override handlers (with OverrideToken)
    - Top-level error handlers (for logging)

    Args:
        violation_type: The specific InvariantViolation subclass to raise.
        operation: Description of the operation that was attempted.
        context: Structured context about the violation (entity IDs, etc.)

    Raises:
        InvariantViolation: Always raises the specified violation type.

    Example:
        raise_invariant_violation(
            PreflightRequired,
            "update_jira_description",
            {"jira_key": "SCRUM-123", "caller": "draft_commit_handler"}
        )
    """
    msg = f"{violation_type.invariant_name}: {operation}"
    raise violation_type(msg, context)


# =============================================================================
# Export all violation types for easy import
# =============================================================================

__all__ = [
    "InvariantViolation",
    "ManagedSectionViolation",
    "PreflightRequired",
    "SlackWriteFromHandler",
    "CommitLogMutation",
    "raise_invariant_violation",
]
