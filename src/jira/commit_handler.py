"""Commit handler for Jira projection."""

import logging
from dataclasses import dataclass
from enum import Enum

from src.domain.entities import ApprovedEntity
from src.domain.content import WorkItemContent, DecisionContent
from src.jira.sync_service import JiraSyncService, DuplicateDetectedError

logger = logging.getLogger(__name__)


class CommitStatus(str, Enum):
    """Result of commit attempt."""
    SUCCESS = "success"
    DUPLICATE_FOUND = "duplicate_found"
    DECISION_NEEDS_TARGET = "decision_needs_target"
    ERROR = "error"


@dataclass(frozen=True)
class CommitResult:
    """Result of commit operation."""
    status: CommitStatus
    jira_key: str | None = None
    duplicate_keys: tuple[str, ...] = ()
    error_message: str | None = None


class CommitHandler:
    """Handles entity commit to Jira.

    Orchestrates the flow:
    1. Validate entity is commitable
    2. Check for duplicates (MANDATORY)
    3. Create Jira issue or report duplicates
    4. Return result for caller to update entity
    """

    def __init__(self, sync_service: JiraSyncService):
        self.sync_service = sync_service

    async def commit_work_item(
        self,
        entity: ApprovedEntity,
        project_key: str,
    ) -> CommitResult:
        """Commit approved work item to Jira.

        ALWAYS checks for duplicates first.

        Args:
            entity: Approved work item
            project_key: Jira project key

        Returns:
            CommitResult with status and jira_key or duplicates
        """
        if not isinstance(entity.content, WorkItemContent):
            return CommitResult(
                status=CommitStatus.ERROR,
                error_message="Entity is not a work item",
            )

        try:
            jira_key = await self.sync_service.commit_work_item(
                entity=entity,
                project_key=project_key,
            )
            logger.info(f"Committed work item {entity.id} as {jira_key}")
            return CommitResult(
                status=CommitStatus.SUCCESS,
                jira_key=jira_key,
            )

        except DuplicateDetectedError as e:
            logger.warning(f"Duplicates found for {entity.id}: {e.duplicate_keys}")
            return CommitResult(
                status=CommitStatus.DUPLICATE_FOUND,
                duplicate_keys=e.duplicate_keys,
            )

        except Exception as e:
            logger.error(f"Failed to commit {entity.id}: {e}")
            return CommitResult(
                status=CommitStatus.ERROR,
                error_message=str(e),
            )

    async def commit_decision(
        self,
        entity: ApprovedEntity,
        target_jira_key: str,
    ) -> CommitResult:
        """Commit approved decision to existing Jira issue.

        Decisions don't create their own issues - they append to
        a linked work item's Jira issue as a comment.

        Args:
            entity: Approved decision
            target_jira_key: Jira issue to append to

        Returns:
            CommitResult with status
        """
        if not isinstance(entity.content, DecisionContent):
            return CommitResult(
                status=CommitStatus.ERROR,
                error_message="Entity is not a decision",
            )

        if not target_jira_key:
            return CommitResult(
                status=CommitStatus.DECISION_NEEDS_TARGET,
                error_message="Decision requires a target Jira issue",
            )

        try:
            await self.sync_service.project_decision(
                entity=entity,
                target_jira_key=target_jira_key,
            )
            logger.info(f"Projected decision {entity.id} to {target_jira_key}")
            return CommitResult(
                status=CommitStatus.SUCCESS,
                jira_key=target_jira_key,
            )

        except Exception as e:
            logger.error(f"Failed to project decision {entity.id}: {e}")
            return CommitResult(
                status=CommitStatus.ERROR,
                error_message=str(e),
            )

    async def commit_with_existing(
        self,
        entity: ApprovedEntity,
        existing_jira_key: str,
    ) -> CommitResult:
        """Link entity to existing Jira issue (user chose from duplicates).

        When duplicates are found and user selects one, use this to
        link instead of creating new.

        Args:
            entity: Approved entity
            existing_jira_key: User-selected existing Jira key

        Returns:
            CommitResult with the linked key
        """
        # Verify the issue exists
        try:
            await self.sync_service.refresh_from_jira(existing_jira_key)
        except Exception as e:
            return CommitResult(
                status=CommitStatus.ERROR,
                error_message=f"Cannot access {existing_jira_key}: {e}",
            )

        logger.info(f"Linking {entity.id} to existing {existing_jira_key}")
        return CommitResult(
            status=CommitStatus.SUCCESS,
            jira_key=existing_jira_key,
        )
