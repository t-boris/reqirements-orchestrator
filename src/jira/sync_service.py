"""Jira sync service for commit and reconciliation."""

import logging
from typing import Any

from src.domain.content import WorkItemContent, DecisionContent, JiraLink
from src.domain.entities import ApprovedEntity, CommittedEntity, DeprecatedEntity, Entity
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
        epic_key: str | None = None,
    ) -> str:
        """Commit approved work item to Jira.

        ALWAYS checks for duplicates before creating.

        Args:
            entity: Approved work item entity
            project_key: Jira project key
            epic_key: Optional Epic issue key to link to (e.g., "PROJ-10")

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

        # Create issue with optional Epic Link
        jira_key = await self.jira.create_issue(
            project_key=project_key,
            summary=content.title,
            issue_type=issue_type,
            description=description,
            epic_key=epic_key,
        )

        logger.info(f"Committed work item {entity.id} as {jira_key}" +
                    (f" (linked to Epic {epic_key})" if epic_key else ""))
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

    async def notify_decision_deprecated(
        self,
        entity: DeprecatedEntity,
        superseding_entity: Entity | None = None,
    ) -> None:
        """Post deprecation notice to Jira when a decision is superseded.

        If the deprecated decision has a jira_link, posts a comment to the
        linked Jira issue noting the decision was superseded.

        Args:
            entity: Deprecated decision entity
            superseding_entity: Optional entity that supersedes this one
        """
        if entity.jira_link is None:
            return

        superseding_content: DecisionContent | None = None
        if (
            superseding_entity is not None
            and isinstance(superseding_entity.content, DecisionContent)
        ):
            superseding_content = superseding_entity.content

        content = entity.content
        if not isinstance(content, DecisionContent):
            return

        comment = self._format_deprecation_comment(content, superseding_content)

        try:
            await self.jira.add_comment(entity.jira_link.jira_key, comment)
            logger.info(
                f"Posted deprecation notice for decision {entity.id} "
                f"to {entity.jira_link.jira_key}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to post deprecation notice for decision {entity.id} "
                f"to {entity.jira_link.jira_key}: {e}"
            )

    async def notify_decision_amended(
        self,
        jira_key: str,
        old_content: DecisionContent,
        new_content: DecisionContent,
        reason: str,
    ) -> None:
        """Post amendment notice to Jira when a decision is amended.

        Args:
            jira_key: Jira issue key to post comment to
            old_content: Previous decision content
            new_content: Updated decision content
            reason: Reason for the amendment
        """
        comment = self._format_amendment_comment(old_content, new_content, reason)

        try:
            await self.jira.add_comment(jira_key, comment)
            logger.info(
                f"Posted amendment notice for decision '{new_content.title}' "
                f"to {jira_key}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to post amendment notice for decision "
                f"'{new_content.title}' to {jira_key}: {e}"
            )

    def _format_deprecation_comment(
        self,
        content: DecisionContent,
        superseding_content: DecisionContent | None = None,
    ) -> str:
        """Format deprecation notice as Jira comment."""
        lines = [
            f"**Decision Superseded: {content.title}**",
            "",
            "This decision has been deprecated.",
        ]

        if superseding_content is not None:
            lines.extend([
                f"Replaced by: **{superseding_content.title}**",
                superseding_content.description[:200],
            ])

        lines.extend(["", "---", "_Updated via MARO_"])

        return "\n".join(lines)

    def _format_amendment_comment(
        self,
        old_content: DecisionContent,
        new_content: DecisionContent,
        reason: str,
    ) -> str:
        """Format amendment notice as Jira comment."""
        lines = [
            f"**Decision Amended: {new_content.title}**",
            "",
            f"Reason: {reason}",
            "",
            f"Previous: {old_content.description[:200]}",
            f"Updated: {new_content.description[:200]}",
            "",
            "---",
            "_Updated via MARO_",
        ]

        return "\n".join(lines)

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
