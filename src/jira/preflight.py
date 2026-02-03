"""Preflight checks before Jira operations."""

import logging
from typing import Any

from src.jira.client import JiraClient
from src.jira.models import (
    FieldConflict,
    FieldOwnership,
    FIELD_OWNERSHIP,
    PreflightCheck,
    PreflightResult,
)

logger = logging.getLogger(__name__)


class PreflightService:
    """Checks for conflicts/duplicates before Jira operations.

    Key responsibility: Prevent accidental duplicate creation by
    searching for existing issues with similar summaries.
    """

    def __init__(self, jira: JiraClient):
        self.jira = jira

    async def check_create(
        self,
        project_key: str,
        summary: str,
        content_hash: str | None = None,
    ) -> PreflightCheck:
        """Check before creating new issue.

        ALWAYS searches for potential duplicates before allowing create.

        Args:
            project_key: Target project
            summary: Issue summary/title
            content_hash: Optional content hash for exact match detection

        Returns:
            PreflightCheck with result and any duplicate keys found
        """
        logger.info(f"Preflight check for create in {project_key}: {summary[:50]}...")

        # Search for potential duplicates by summary
        duplicates = await self.jira.search_duplicates(project_key, summary)

        if duplicates:
            logger.warning(f"Potential duplicates found: {duplicates}")
            return PreflightCheck(
                result=PreflightResult.DUPLICATE,
                details=f"Found {len(duplicates)} potential duplicate(s): {', '.join(duplicates)}",
                duplicate_keys=tuple(duplicates),
            )

        return PreflightCheck(
            result=PreflightResult.OK,
            details="No duplicates found, safe to create",
        )

    async def check_update(
        self,
        jira_key: str,
        local_values: dict[str, Any],
    ) -> PreflightCheck:
        """Check before updating existing issue.

        Compares local values with Jira values to detect conflicts.
        Uses field ownership to determine which conflicts matter.

        Args:
            jira_key: Issue to update
            local_values: Fields we want to update with local values

        Returns:
            PreflightCheck with any conflicts detected
        """
        logger.info(f"Preflight check for update: {jira_key}")

        try:
            issue = await self.jira.get_issue(jira_key)
        except Exception as e:
            return PreflightCheck(
                result=PreflightResult.CONFLICT,
                details=f"Failed to fetch issue {jira_key}: {e}",
            )

        jira_fields = issue.get("fields", {})
        conflicts: list[FieldConflict] = []

        for field, local_value in local_values.items():
            jira_value = jira_fields.get(field)
            ownership = FIELD_OWNERSHIP.get(field, FieldOwnership.SHARED)

            if ownership == FieldOwnership.JIRA_OWNED:
                # Can't update Jira-owned fields
                if local_value != jira_value:
                    conflicts.append(FieldConflict(
                        field=field,
                        slack_value=local_value,
                        jira_value=jira_value,
                        ownership=ownership,
                    ))

            elif ownership == FieldOwnership.SHARED:
                # Check for divergence on shared fields
                if local_value != jira_value:
                    conflicts.append(FieldConflict(
                        field=field,
                        slack_value=local_value,
                        jira_value=jira_value,
                        ownership=ownership,
                    ))

            # SLACK_OWNED fields: we can always update, no conflict check

        if conflicts:
            return PreflightCheck(
                result=PreflightResult.CONFLICT,
                details=f"{len(conflicts)} field conflict(s) detected",
                conflicts=tuple(conflicts),
            )

        return PreflightCheck(
            result=PreflightResult.OK,
            details="No conflicts, safe to update",
        )
