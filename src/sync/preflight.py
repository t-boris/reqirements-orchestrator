"""Preflight Sync service for detecting Jira conflicts before operations.

Implements the 4-type conflict classification from phase-29-CONTEXT.md:
1. Idempotent - Operation already done, auto-success
2. Safe Drift - Non-overlapping changes, ask but default proceed
3. Real Conflict - Overlapping field changes, block + choice
4. Structural - Impossible operation, block + explain
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.db.jira_registry import JiraIssueLink, JiraRegistryStore
    from src.jira.client import JiraService

logger = logging.getLogger(__name__)


class ConflictType(str, Enum):
    """Preflight conflict classification per CONTEXT.md."""

    IDEMPOTENT = "idempotent"  # Operation already done, auto-success
    SAFE_DRIFT = "safe_drift"  # Non-overlapping changes, ask but default proceed
    REAL_CONFLICT = "real_conflict"  # Overlapping field changes, block + choice
    STRUCTURAL = "structural"  # Impossible operation, block + explain


@dataclass
class FieldChange:
    """A detected field change between local and Jira."""

    field: str  # summary, status, assignee, etc.
    local_value: Optional[str]
    jira_value: Optional[str]
    changed_by: Optional[str]  # Jira account ID who changed
    changed_at: Optional[datetime]  # When changed in Jira


@dataclass
class PreflightResult:
    """Result of preflight check before Jira operation."""

    conflict_type: ConflictType
    jira_key: str
    intended_operation: str  # "transition", "update", "create"
    intended_fields: list[str]  # Fields the operation would modify
    detected_changes: list[FieldChange]  # Changes found in Jira
    overlapping_fields: list[str]  # Fields both local and Jira modified
    message: str  # Human-readable explanation
    can_proceed: bool  # True for IDEMPOTENT (auto), False for others
    needs_choice: bool  # True for SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL


class PreflightService:
    """Service for preflight checks before Jira operations.

    Philosophy from CONTEXT.md:
    - Never auto-write, never auto-fix
    - Only: stop -> show -> wait for choice
    - Exception: IDEMPOTENT is auto-success (operation already done)
    """

    def __init__(
        self,
        jira_service: "JiraService",
        registry: "JiraRegistryStore",
    ) -> None:
        """Initialize PreflightService.

        Args:
            jira_service: JiraService for fetching fresh Jira data.
            registry: JiraRegistryStore for local registry lookups.
        """
        self._jira = jira_service
        self._registry = registry

    async def check_transition(
        self,
        channel_id: str,
        jira_key: str,
        target_status: str,
    ) -> PreflightResult:
        """Check before status transition.

        Classification:
        - IDEMPOTENT: Already at target status
        - STRUCTURAL: Transition not allowed (e.g., Done -> Cancelled not in workflow)
        - SAFE_DRIFT: Other fields changed, but status transition still valid
        - REAL_CONFLICT: Status was changed to different value externally

        Args:
            channel_id: Slack channel ID.
            jira_key: Jira issue key (e.g., "SCRUM-123").
            target_status: Target status name (e.g., "Done").

        Returns:
            PreflightResult with conflict classification.
        """
        local_link, jira_issue, changes = await self._fetch_and_compare(
            channel_id, jira_key
        )

        # Handle missing issue
        if jira_issue is None:
            return PreflightResult(
                conflict_type=ConflictType.STRUCTURAL,
                jira_key=jira_key,
                intended_operation="transition",
                intended_fields=["status"],
                detected_changes=[],
                overlapping_fields=[],
                message=f"{jira_key} not found in Jira. It may have been deleted.",
                can_proceed=False,
                needs_choice=True,
            )

        current_status = jira_issue.status

        # IDEMPOTENT: Already at target status
        if current_status.lower() == target_status.lower():
            return PreflightResult(
                conflict_type=ConflictType.IDEMPOTENT,
                jira_key=jira_key,
                intended_operation="transition",
                intended_fields=["status"],
                detected_changes=changes,
                overlapping_fields=[],
                message=f"{jira_key} is already {current_status} in Jira.",
                can_proceed=True,
                needs_choice=False,
            )

        # Check for status conflict (external status change)
        status_changes = [c for c in changes if c.field == "status"]
        if status_changes:
            status_change = status_changes[0]
            # Status changed externally to something other than target
            if status_change.jira_value and status_change.jira_value.lower() != target_status.lower():
                # Check if it's a structural conflict (status incompatible)
                # For now, treat any external status change as REAL_CONFLICT
                # Future: could check Jira workflow for valid transitions
                return PreflightResult(
                    conflict_type=ConflictType.REAL_CONFLICT,
                    jira_key=jira_key,
                    intended_operation="transition",
                    intended_fields=["status"],
                    detected_changes=changes,
                    overlapping_fields=["status"],
                    message=(
                        f"{jira_key} status was changed externally.\n"
                        f"Expected: {status_change.local_value or 'unknown'}\n"
                        f"Current: {status_change.jira_value}\n"
                        f"You wanted: {target_status}"
                    ),
                    can_proceed=False,
                    needs_choice=True,
                )

        # No status conflict - check for safe drift
        non_status_changes = [c for c in changes if c.field != "status"]
        if non_status_changes:
            return PreflightResult(
                conflict_type=ConflictType.SAFE_DRIFT,
                jira_key=jira_key,
                intended_operation="transition",
                intended_fields=["status"],
                detected_changes=changes,
                overlapping_fields=[],
                message=(
                    f"{jira_key} was updated in Jira since last sync.\n"
                    f"Fields changed: {', '.join(c.field for c in non_status_changes)}.\n"
                    f"Your operation affects: status.\n"
                    f"No overlap detected."
                ),
                can_proceed=False,
                needs_choice=True,
            )

        # No changes detected - proceed (shouldn't reach here if changes empty)
        return PreflightResult(
            conflict_type=ConflictType.SAFE_DRIFT,
            jira_key=jira_key,
            intended_operation="transition",
            intended_fields=["status"],
            detected_changes=changes,
            overlapping_fields=[],
            message=f"{jira_key} is ready for transition to {target_status}.",
            can_proceed=False,
            needs_choice=True,
        )

    async def check_update(
        self,
        channel_id: str,
        jira_key: str,
        fields_to_update: dict[str, str],
    ) -> PreflightResult:
        """Check before field update.

        Classification:
        - IDEMPOTENT: Fields already have target values
        - SAFE_DRIFT: Jira changed other fields, not overlapping
        - REAL_CONFLICT: Jira changed same fields we want to update

        Args:
            channel_id: Slack channel ID.
            jira_key: Jira issue key.
            fields_to_update: Dict of field name to new value.

        Returns:
            PreflightResult with conflict classification.
        """
        local_link, jira_issue, changes = await self._fetch_and_compare(
            channel_id, jira_key
        )

        intended_fields = list(fields_to_update.keys())

        # Handle missing issue
        if jira_issue is None:
            return PreflightResult(
                conflict_type=ConflictType.STRUCTURAL,
                jira_key=jira_key,
                intended_operation="update",
                intended_fields=intended_fields,
                detected_changes=[],
                overlapping_fields=[],
                message=f"{jira_key} not found in Jira. It may have been deleted.",
                can_proceed=False,
                needs_choice=True,
            )

        # Check for idempotent (all fields already at target values)
        all_idempotent = True
        for field, target_value in fields_to_update.items():
            current_value = self._get_current_field_value(jira_issue, field)
            if current_value != target_value:
                all_idempotent = False
                break

        if all_idempotent:
            return PreflightResult(
                conflict_type=ConflictType.IDEMPOTENT,
                jira_key=jira_key,
                intended_operation="update",
                intended_fields=intended_fields,
                detected_changes=changes,
                overlapping_fields=[],
                message=f"{jira_key} already has the target values in Jira.",
                can_proceed=True,
                needs_choice=False,
            )

        # Check for overlapping changes
        changed_fields = {c.field for c in changes}
        overlapping = [f for f in intended_fields if f in changed_fields]

        if overlapping:
            return PreflightResult(
                conflict_type=ConflictType.REAL_CONFLICT,
                jira_key=jira_key,
                intended_operation="update",
                intended_fields=intended_fields,
                detected_changes=changes,
                overlapping_fields=overlapping,
                message=(
                    f"Conflict detected for {jira_key}.\n"
                    f"Both Jira and Channel modified: {', '.join(overlapping)}."
                ),
                can_proceed=False,
                needs_choice=True,
            )

        # Non-overlapping changes - safe drift
        if changes:
            return PreflightResult(
                conflict_type=ConflictType.SAFE_DRIFT,
                jira_key=jira_key,
                intended_operation="update",
                intended_fields=intended_fields,
                detected_changes=changes,
                overlapping_fields=[],
                message=(
                    f"{jira_key} was updated in Jira since last sync.\n"
                    f"Fields changed: {', '.join(c.field for c in changes)}.\n"
                    f"Your operation affects: {', '.join(intended_fields)}.\n"
                    f"No overlap detected."
                ),
                can_proceed=False,
                needs_choice=True,
            )

        # No changes detected - safe to proceed
        return PreflightResult(
            conflict_type=ConflictType.SAFE_DRIFT,
            jira_key=jira_key,
            intended_operation="update",
            intended_fields=intended_fields,
            detected_changes=[],
            overlapping_fields=[],
            message=f"{jira_key} is ready for update.",
            can_proceed=False,
            needs_choice=True,
        )

    async def _fetch_and_compare(
        self,
        channel_id: str,
        jira_key: str,
    ) -> tuple[Optional["JiraIssueLink"], Optional["JiraIssue"], list[FieldChange]]:
        """Fetch local registry and Jira data, detect changes.

        Args:
            channel_id: Slack channel ID.
            jira_key: Jira issue key.

        Returns:
            Tuple of (local_link, jira_issue, detected_changes).
            jira_issue is None if not found in Jira.
        """
        from src.jira.client import JiraAPIError
        from src.jira.types import JiraIssue

        # Get local registry entry
        local_link = await self._registry.get_link(channel_id, jira_key)

        # Fetch fresh data from Jira
        jira_issue: Optional[JiraIssue] = None
        try:
            jira_issue = await self._jira.get_issue(jira_key)
        except JiraAPIError as e:
            if e.status_code == 404:
                logger.warning(f"Jira issue {jira_key} not found (404)")
                # Mark as deleted in registry if we have a local entry
                if local_link:
                    await self._registry.mark_deleted(channel_id, jira_key)
                return local_link, None, []
            raise

        # Compare and detect changes
        changes: list[FieldChange] = []

        if local_link:
            # Compare status
            if local_link.status and jira_issue.status:
                if local_link.status.lower() != jira_issue.status.lower():
                    changes.append(
                        FieldChange(
                            field="status",
                            local_value=local_link.status,
                            jira_value=jira_issue.status,
                            changed_by=None,  # Would need changelog API
                            changed_at=None,
                        )
                    )

            # Compare assignee
            if local_link.assignee != jira_issue.assignee:
                changes.append(
                    FieldChange(
                        field="assignee",
                        local_value=local_link.assignee,
                        jira_value=jira_issue.assignee,
                        changed_by=None,
                        changed_at=None,
                    )
                )

            # Compare summary
            if local_link.summary and jira_issue.summary:
                if local_link.summary != jira_issue.summary:
                    changes.append(
                        FieldChange(
                            field="summary",
                            local_value=local_link.summary,
                            jira_value=jira_issue.summary,
                            changed_by=None,
                            changed_at=None,
                        )
                    )

            # Update registry with fresh data (always sync on preflight)
            await self._registry.update_from_jira(
                channel_id=channel_id,
                jira_key=jira_key,
                summary=jira_issue.summary,
                status=jira_issue.status,
                assignee=jira_issue.assignee,
                issue_type=local_link.issue_type or "story",  # Preserve existing
                jira_updated=datetime.now(),  # Jira API doesn't return updated in get_issue
            )

        return local_link, jira_issue, changes

    def _get_current_field_value(
        self,
        jira_issue: "JiraIssue",
        field: str,
    ) -> Optional[str]:
        """Get current value of a field from Jira issue.

        Args:
            jira_issue: JiraIssue from API.
            field: Field name.

        Returns:
            Field value as string, or None.
        """
        from src.jira.types import JiraIssue

        if field == "summary":
            return jira_issue.summary
        elif field == "status":
            return jira_issue.status
        elif field == "assignee":
            return jira_issue.assignee
        elif field == "description":
            return jira_issue.description
        return None
