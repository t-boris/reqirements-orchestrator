"""Reconciliation service for Jira sync."""

import logging
from dataclasses import dataclass
from enum import Enum

from src.domain.entities import CommittedEntity
from src.jira.models import FieldOwnership, SyncDiscrepancy
from src.jira.sync_service import JiraSyncService

logger = logging.getLogger(__name__)


class ResolutionChoice(str, Enum):
    """User choice for resolving discrepancy."""
    USE_JIRA = "use_jira"
    KEEP_SLACK = "keep_slack"
    SKIP = "skip"


@dataclass(frozen=True)
class ReconciliationReport:
    """Report from reconciliation check."""
    total_checked: int
    in_sync: int
    discrepancies: tuple[SyncDiscrepancy, ...]
    errors: tuple[str, ...]

    @property
    def has_discrepancies(self) -> bool:
        return len(self.discrepancies) > 0

    @property
    def summary(self) -> str:
        if not self.has_discrepancies:
            return f"All {self.total_checked} entities in sync with Jira"
        return f"{len(self.discrepancies)} discrepancies found in {self.total_checked} entities"


class ReconciliationService:
    """Handles reconciliation between Slack entities and Jira.

    Wraps JiraSyncService.reconcile() with:
    - User-friendly reporting
    - Resolution tracking
    - Conflict resolution orchestration
    """

    def __init__(self, sync_service: JiraSyncService):
        self.sync_service = sync_service

    async def check_sync_status(
        self,
        entities: list[CommittedEntity],
    ) -> ReconciliationReport:
        """Check sync status for committed entities.

        Args:
            entities: Committed entities to check

        Returns:
            ReconciliationReport with discrepancies
        """
        if not entities:
            return ReconciliationReport(
                total_checked=0,
                in_sync=0,
                discrepancies=(),
                errors=(),
            )

        logger.info(f"Checking sync status for {len(entities)} entities")

        discrepancies = await self.sync_service.reconcile(entities)

        # Group by entity to count in-sync
        entities_with_issues = set(d.entity_id for d in discrepancies)
        in_sync = len(entities) - len(entities_with_issues)

        return ReconciliationReport(
            total_checked=len(entities),
            in_sync=in_sync,
            discrepancies=tuple(discrepancies),
            errors=(),
        )

    async def refresh_single(
        self,
        entity: CommittedEntity,
    ) -> ReconciliationReport:
        """Refresh a single entity from Jira.

        Args:
            entity: Entity to refresh

        Returns:
            ReconciliationReport for single entity
        """
        return await self.check_sync_status([entity])

    def format_discrepancy(self, d: SyncDiscrepancy) -> str:
        """Format discrepancy for display.

        Args:
            d: Discrepancy to format

        Returns:
            Human-readable string
        """
        ownership_note = ""
        if d.ownership == FieldOwnership.JIRA_OWNED:
            ownership_note = " (Jira-owned field)"
        elif d.ownership == FieldOwnership.SLACK_OWNED:
            ownership_note = " (Slack-owned field)"

        return (
            f"*{d.field}*{ownership_note}\n"
            f"  Slack: `{d.slack_value}`\n"
            f"  Jira: `{d.jira_value}`"
        )

    def get_resolution_recommendation(self, d: SyncDiscrepancy) -> ResolutionChoice:
        """Get recommended resolution based on field ownership.

        Args:
            d: Discrepancy to evaluate

        Returns:
            Recommended resolution
        """
        if d.ownership == FieldOwnership.JIRA_OWNED:
            return ResolutionChoice.USE_JIRA
        elif d.ownership == FieldOwnership.SLACK_OWNED:
            return ResolutionChoice.KEEP_SLACK
        else:
            # SHARED - no recommendation, user decides
            return ResolutionChoice.SKIP
