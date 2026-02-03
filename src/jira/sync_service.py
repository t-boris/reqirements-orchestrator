"""Jira sync service for commit and reconciliation."""

import logging
from typing import Any

from src.domain.content import WorkItemContent, DecisionContent, JiraLink
from src.domain.entities import ApprovedEntity, CommittedEntity
from src.domain.types import JiraKey, SyncStatus
from src.jira.client import JiraClient
from src.jira.models import (
    FieldOwnership,
    FIELD_OWNERSHIP,
    PreflightResult,
    SyncDiscrepancy,
)
from src.jira.preflight import PreflightService

logger = logging.getLogger(__name__)


class JiraSyncError(Exception):
    """Error during Jira sync operation."""
    pass


class DuplicateDetectedError(JiraSyncError):
    """Duplicate issue detected during preflight."""

    def __init__(self, message: str, duplicate_keys: tuple[str, ...]):
        super().__init__(message)
        self.duplicate_keys = duplicate_keys


class ConflictDetectedError(JiraSyncError):
    """Conflict detected during preflight."""
    pass


class JiraSyncService:
    """Handles Jira sync operations.

    Responsibilities:
    - Create Jira issues for approved work items (with duplicate check)
    - Project decisions to existing Jira issues as comments
    - Reconcile committed entities with Jira state
    """

    def __init__(self, jira: JiraClient, preflight: PreflightService):
        self.jira = jira
        self.preflight = preflight

    async def commit_work_item(
        self,
        entity: ApprovedEntity,
        project_key: str,
    ) -> str:
        """Commit approved work item to Jira.

        ALWAYS checks for duplicates before creating.

        Args:
            entity: Approved work item entity
            project_key: Jira project key

        Returns:
            Created Jira issue key

        Raises:
            DuplicateDetectedError: If potential duplicates found
            JiraSyncError: If creation fails
        """
        if not isinstance(entity.content, WorkItemContent):
            raise JiraSyncError("Entity content is not a WorkItemContent")

        content: WorkItemContent = entity.content

        # ALWAYS check for duplicates first
        preflight_result = await self.preflight.check_create(
            project_key=project_key,
            summary=content.title,
        )

        if preflight_result.result == PreflightResult.DUPLICATE:
            raise DuplicateDetectedError(
                preflight_result.details,
                preflight_result.duplicate_keys,
            )

        # Map issue type
        issue_type = self._map_issue_type(content.issue_type)

        # Build description
        description = content.description or ""
        if content.acceptance_criteria:
            ac_text = "\n".join(f"- [ ] {ac}" for ac in content.acceptance_criteria)
            description += f"\n\n## Acceptance Criteria\n{ac_text}"

        # Create issue
        jira_key = await self.jira.create_issue(
            project_key=project_key,
            summary=content.title,
            issue_type=issue_type,
            description=description,
        )

        logger.info(f"Committed work item {entity.id} as {jira_key}")
        return jira_key

    async def project_decision(
        self,
        entity: ApprovedEntity,
        target_jira_key: str,
    ) -> None:
        """Project decision to existing Jira issue as comment.

        Per CONTEXT.md: Decisions don't create their own Jira issues.
        Instead, they append to a linked work item's Jira issue.

        Args:
            entity: Approved decision entity
            target_jira_key: Jira issue to append to

        Raises:
            JiraSyncError: If projection fails
        """
        if not isinstance(entity.content, DecisionContent):
            raise JiraSyncError("Entity content is not a DecisionContent")

        content: DecisionContent = entity.content

        # Format decision as comment
        comment = self._format_decision_comment(content)

        # Add as comment
        await self.jira.add_comment(target_jira_key, comment)

        logger.info(f"Projected decision {entity.id} to {target_jira_key}")

    async def refresh_from_jira(
        self,
        jira_key: str,
    ) -> dict[str, Any]:
        """Fetch current state from Jira.

        Args:
            jira_key: Issue to refresh

        Returns:
            Issue data from Jira
        """
        return await self.jira.get_issue(jira_key)

    async def reconcile(
        self,
        committed_entities: list[CommittedEntity],
    ) -> list[SyncDiscrepancy]:
        """Compare committed entities with Jira state.

        Finds discrepancies between Slack (source of truth for content)
        and Jira (source of truth for workflow fields).

        Args:
            committed_entities: Entities to check

        Returns:
            List of discrepancies found
        """
        discrepancies: list[SyncDiscrepancy] = []

        for entity in committed_entities:
            if entity.jira_link is None:
                continue

            jira_key = entity.jira_link.jira_key

            try:
                issue = await self.jira.get_issue(jira_key)
                jira_fields = issue.get("fields", {})

                # Compare fields based on ownership
                entity_discrepancies = self._compare_entity_to_jira(
                    entity, jira_fields
                )
                discrepancies.extend(entity_discrepancies)

            except Exception as e:
                # Issue not accessible - report as discrepancy
                discrepancies.append(SyncDiscrepancy(
                    entity_id=str(entity.id),
                    jira_key=jira_key,
                    field="__access__",
                    slack_value="entity exists",
                    jira_value=f"error: {e}",
                    ownership=FieldOwnership.SHARED,
                ))

        return discrepancies

    def _compare_entity_to_jira(
        self,
        entity: CommittedEntity,
        jira_fields: dict[str, Any],
    ) -> list[SyncDiscrepancy]:
        """Compare entity fields to Jira fields."""
        discrepancies: list[SyncDiscrepancy] = []

        if not isinstance(entity.content, (WorkItemContent, DecisionContent)):
            return discrepancies

        content = entity.content

        # Compare summary
        if hasattr(content, "title"):
            jira_summary = jira_fields.get("summary", "")
            if content.title != jira_summary:
                discrepancies.append(SyncDiscrepancy(
                    entity_id=str(entity.id),
                    jira_key=entity.jira_link.jira_key,
                    field="summary",
                    slack_value=content.title,
                    jira_value=jira_summary,
                    ownership=FIELD_OWNERSHIP.get("summary", FieldOwnership.SLACK_OWNED),
                ))

        # Compare description (if work item)
        if isinstance(content, WorkItemContent) and content.description:
            jira_desc = jira_fields.get("description", "") or ""
            # Only flag if Jira description doesn't contain our content
            # (Jira may have additional content we didn't write)
            if content.description not in jira_desc:
                discrepancies.append(SyncDiscrepancy(
                    entity_id=str(entity.id),
                    jira_key=entity.jira_link.jira_key,
                    field="description",
                    slack_value=content.description[:100] + "...",
                    jira_value=jira_desc[:100] + "..." if jira_desc else "(empty)",
                    ownership=FIELD_OWNERSHIP.get("description", FieldOwnership.SLACK_OWNED),
                ))

        return discrepancies

    def _map_issue_type(self, issue_type) -> str:
        """Map internal issue type to Jira issue type name."""
        # Handle IssueType enum or string
        type_str = issue_type.value if hasattr(issue_type, "value") else str(issue_type)
        return {
            "epic": "Epic",
            "story": "Story",
            "task": "Task",
            "bug": "Bug",
            "spike": "Spike",
        }.get(type_str.lower(), "Task")

    def _format_decision_comment(self, content: DecisionContent) -> str:
        """Format decision as Jira comment."""
        lines = [
            f"**Decision: {content.title}**",
            f"Type: {content.decision_type.value if hasattr(content.decision_type, 'value') else content.decision_type}",
            "",
            content.description or "(no description)",
        ]

        if content.rationale:
            lines.extend(["", f"*Rationale:* {content.rationale}"])

        lines.extend(["", "---", "_Recorded via MARO_"])

        return "\n".join(lines)
