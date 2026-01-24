"""Decision -> Jira synchronization service.

Philosophy from CONTEXT.md:
- Decision approval = commit + immediate Jira update
- Every sync goes through preflight (no exceptions)
- Managed sections: MARO writes only to its own block

Flow:
1. Approval triggers sync
2. Preflight checks all linked tickets
3. If all safe -> atomic apply to all
4. If any conflict -> report for resolution
5. Update sync version in links
"""
import logging
from dataclasses import dataclass
from typing import Optional

from src.db.decision_link_store import DecisionLinkStore
from src.db.decision_store import DecisionStore
from src.jira.client import JiraService
from src.jira.managed_sections import update_description_with_managed_section
from src.schemas.decision import Decision
from src.sync.decision_preflight import DecisionPreflightService, DecisionPreflightResult
from src.sync.preflight import ConflictType

logger = logging.getLogger(__name__)


@dataclass
class SyncTicketResult:
    """Result of syncing decision to a single ticket."""
    jira_key: str
    success: bool
    error: Optional[str] = None
    preflight_result: Optional[DecisionPreflightResult] = None


@dataclass
class DecisionSyncResult:
    """Result of syncing decision to all linked tickets."""
    decision_id: str
    version: int
    total_tickets: int
    synced_count: int
    failed_count: int
    blocked_count: int  # Blocked by preflight
    ticket_results: list[SyncTicketResult]

    @property
    def all_synced(self) -> bool:
        return self.synced_count == self.total_tickets

    @property
    def has_conflicts(self) -> bool:
        return self.blocked_count > 0


class DecisionSyncService:
    """Service for projecting decisions to Jira tickets.

    ARCHITECTURE:
    - Database is truth
    - Jira is projection (this service writes to Jira)
    - Slack is presentation (NOT this service's concern)

    This service does NOT depend on Slack message state.
    Jira sync proceeds even if canonical message update failed.

    Handles:
    - Preflight checks for all linked tickets
    - Atomic sync (all or none, with partial tolerance)
    - Update tracking in DecisionLink
    """

    def __init__(
        self,
        jira_service: JiraService,
        decision_store: DecisionStore,
        link_store: DecisionLinkStore,
    ):
        self._jira = jira_service
        self._decisions = decision_store
        self._links = link_store
        self._preflight = DecisionPreflightService(
            jira_service=jira_service,
            decision_store=decision_store,
            link_store=link_store,
        )

    async def sync_decision(
        self,
        decision_id: str,
        force: bool = False,
    ) -> DecisionSyncResult:
        """Sync decision to all linked Jira tickets.

        NOTE: This method does NOT depend on Slack message state.
        Jira sync proceeds even if canonical message update failed.
        Architecture: Database (truth) → Jira (projection) → Slack (presentation)

        Steps:
        1. Get decision and all links
        2. Run preflight on all tickets
        3. If any blocked and not force -> return with conflicts
        4. Apply to all safe tickets
        5. Update sync version in links
        6. Return result summary

        Args:
            decision_id: Decision UUID
            force: If True, skip conflicts (still respect STRUCTURAL)

        Returns:
            DecisionSyncResult with per-ticket outcomes
        """
        # Get decision
        decision = await self._decisions.get(decision_id)
        if not decision:
            return DecisionSyncResult(
                decision_id=decision_id,
                version=0,
                total_tickets=0,
                synced_count=0,
                failed_count=0,
                blocked_count=0,
                ticket_results=[],
            )

        # Get all links
        links = await self._links.get_links_for_decision(decision_id)
        if not links:
            return DecisionSyncResult(
                decision_id=decision_id,
                version=decision.version,
                total_tickets=0,
                synced_count=0,
                failed_count=0,
                blocked_count=0,
                ticket_results=[],
            )

        # Run preflight on all tickets
        preflight_results = await self._preflight.check_batch_sync(decision)

        # Classify results
        ticket_results: list[SyncTicketResult] = []
        synced = 0
        failed = 0
        blocked = 0

        for pr in preflight_results:
            if pr.conflict_type == ConflictType.STRUCTURAL:
                # Can't sync to deleted/missing tickets
                ticket_results.append(SyncTicketResult(
                    jira_key=pr.jira_key,
                    success=False,
                    error=pr.message,
                    preflight_result=pr,
                ))
                failed += 1
                continue

            if pr.conflict_type == ConflictType.REAL_CONFLICT and not force:
                # Blocked by conflict
                ticket_results.append(SyncTicketResult(
                    jira_key=pr.jira_key,
                    success=False,
                    error="Conflict detected, requires resolution",
                    preflight_result=pr,
                ))
                blocked += 1
                continue

            # Safe to sync (IDEMPOTENT, SAFE_DRIFT, or forced REAL_CONFLICT)
            if pr.conflict_type == ConflictType.IDEMPOTENT:
                # Already synced, skip
                ticket_results.append(SyncTicketResult(
                    jira_key=pr.jira_key,
                    success=True,
                    preflight_result=pr,
                ))
                synced += 1
                continue

            # Apply sync
            try:
                await self._apply_sync(decision, pr.jira_key)
                await self._links.mark_synced(
                    decision_id=decision_id,
                    jira_key=pr.jira_key,
                    version=decision.version,
                )
                ticket_results.append(SyncTicketResult(
                    jira_key=pr.jira_key,
                    success=True,
                    preflight_result=pr,
                ))
                synced += 1

            except Exception as e:
                logger.error(
                    "Failed to sync decision to ticket",
                    extra={
                        "decision_id": decision_id,
                        "jira_key": pr.jira_key,
                        "error": str(e),
                    }
                )
                ticket_results.append(SyncTicketResult(
                    jira_key=pr.jira_key,
                    success=False,
                    error=str(e),
                    preflight_result=pr,
                ))
                failed += 1

        return DecisionSyncResult(
            decision_id=decision_id,
            version=decision.version,
            total_tickets=len(links),
            synced_count=synced,
            failed_count=failed,
            blocked_count=blocked,
            ticket_results=ticket_results,
        )

    async def _apply_sync(
        self,
        decision: Decision,
        jira_key: str,
    ) -> None:
        """Apply decision to a single Jira ticket.

        Updates description using managed sections pattern.
        """
        # Get current issue
        issue = await self._jira.get_issue(jira_key)
        current_description = issue.description or ""

        # Get all decisions linked to this ticket
        all_links = await self._links.get_decisions_for_ticket(jira_key)
        decision_ids = [link.decision_id for link in all_links]

        # Fetch all linked decisions
        decisions = []
        for did in decision_ids:
            d = await self._decisions.get(did)
            if d:
                decisions.append(d)

        # Update description with managed section
        new_description = update_description_with_managed_section(
            current_description,
            decisions,
        )

        # Apply update
        await self._jira.update_issue(
            issue_key=jira_key,
            updates={"description": new_description},
        )

        logger.info(
            "Synced decision to Jira",
            extra={
                "decision_id": decision.id,
                "jira_key": jira_key,
                "version": decision.version,
            }
        )
