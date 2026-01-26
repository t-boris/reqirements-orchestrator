"""Impact Analysis Service for decision change operations.

Computes which entities are affected when a decision changes.
This analysis runs automatically when a change operation is created.

Impact analysis shows:
- Which Jira issues reference this decision
- Which pinned messages/indexes depend on it
- Preflight conflicts (Jira updated externally?)
- Risk level: how many objects, which fields

Phase 41: Decision Change Propagation
"""
import logging
from typing import TYPE_CHECKING

from src.schemas.decision import (
    Decision,
    DecisionChangeOp,
    DecisionChangeOpType,
    ImpactSummary,
    ImpactTicket,
)
from src.sync.decision_preflight import DecisionPreflightService
from src.sync.preflight import ConflictType

if TYPE_CHECKING:
    from src.db.decision_change_op_store import DecisionChangeOpStore
    from src.db.decision_link_store import DecisionLinkStore
    from src.db.decision_store import DecisionStore
    from src.jira.client import JiraService

logger = logging.getLogger(__name__)


class ImpactAnalysisService:
    """Service for computing impact of decision changes.

    Analyzes all linked tickets when a decision change is proposed,
    running preflight on each to detect conflicts before applying.

    Usage:
        service = ImpactAnalysisService(jira_service, link_store, decision_store)
        impact = await service.analyze(decision, DecisionChangeOpType.EDIT)
    """

    def __init__(
        self,
        jira_service: "JiraService",
        link_store: "DecisionLinkStore",
        decision_store: "DecisionStore",
    ) -> None:
        """Initialize ImpactAnalysisService.

        Args:
            jira_service: JiraService for API calls during preflight
            link_store: DecisionLinkStore for getting linked tickets
            decision_store: DecisionStore for decision lookups
        """
        self._jira = jira_service
        self._links = link_store
        self._decisions = decision_store
        self._preflight = DecisionPreflightService(
            jira_service=jira_service,
            decision_store=decision_store,
            link_store=link_store,
        )

    async def analyze(
        self,
        decision: Decision,
        operation: DecisionChangeOpType,
    ) -> ImpactSummary:
        """Analyze impact of a decision change.

        Steps:
        1. Get all links for the decision
        2. Run preflight on each linked ticket
        3. Classify results (synced/pending/conflict/structural)
        4. Compute risk level
        5. Return ImpactSummary

        Args:
            decision: The decision being changed
            operation: Type of change operation

        Returns:
            ImpactSummary with full analysis results
        """
        # Get all links
        links = await self._links.get_links_for_decision(decision.id)

        if not links:
            logger.info(
                "No links found for decision",
                extra={"decision_id": decision.id},
            )
            return ImpactSummary(
                total_affected=0,
                has_jira_writes=False,
                risk_level="none",
            )

        # Run preflight on all linked tickets
        preflight_results = await self._preflight.check_batch_sync(decision)

        # Build impact tickets from preflight results
        tickets: list[ImpactTicket] = []
        conflict_count = 0
        pending_count = 0
        safe_count = 0

        for pr in preflight_results:
            if pr.conflict_type == ConflictType.STRUCTURAL:
                tickets.append(
                    ImpactTicket(
                        jira_key=pr.jira_key,
                        sync_status="structural",
                        conflict_type=pr.conflict_type.value,
                        message=pr.message,
                    )
                )
                conflict_count += 1
            elif pr.conflict_type == ConflictType.REAL_CONFLICT:
                tickets.append(
                    ImpactTicket(
                        jira_key=pr.jira_key,
                        sync_status="conflict",
                        conflict_type=pr.conflict_type.value,
                        message=pr.message,
                    )
                )
                conflict_count += 1
            elif pr.conflict_type == ConflictType.IDEMPOTENT:
                # Find the link to get last synced version
                link = next((l for l in links if l.jira_key == pr.jira_key), None)
                tickets.append(
                    ImpactTicket(
                        jira_key=pr.jira_key,
                        sync_status="synced",
                        last_synced_version=link.synced_version if link else None,
                    )
                )
                safe_count += 1
            else:  # SAFE_DRIFT - needs sync
                link = next((l for l in links if l.jira_key == pr.jira_key), None)
                tickets.append(
                    ImpactTicket(
                        jira_key=pr.jira_key,
                        sync_status="pending",
                        last_synced_version=link.synced_version if link else None,
                        message=pr.message,
                    )
                )
                pending_count += 1

        # Deprecate operation always writes to Jira (clears managed sections)
        has_jira_writes = pending_count > 0 or operation == DecisionChangeOpType.DEPRECATE

        impact = ImpactSummary(
            jira_keys=[t.jira_key for t in tickets],
            tickets=tickets,
            conflict_count=conflict_count,
            pending_count=pending_count,
            safe_count=safe_count,
            total_affected=len(tickets),
            has_jira_writes=has_jira_writes,
        )

        # Compute and set risk level
        impact.risk_level = self._compute_risk_level(impact)

        logger.info(
            "Impact analysis complete",
            extra={
                "decision_id": decision.id,
                "operation": operation.value,
                "total_affected": impact.total_affected,
                "conflict_count": impact.conflict_count,
                "pending_count": impact.pending_count,
                "safe_count": impact.safe_count,
                "risk_level": impact.risk_level,
            },
        )

        return impact

    def _compute_risk_level(self, impact: ImpactSummary) -> str:
        """Compute risk level based on impact analysis.

        Risk levels:
        - none: no affected entities
        - low: 1-3 synced tickets, no conflicts
        - medium: 4-10 tickets OR any pending syncs
        - high: 10+ tickets OR any conflicts OR structural issues

        Args:
            impact: The impact summary to analyze

        Returns:
            Risk level string: "none", "low", "medium", or "high"
        """
        # None: no affected entities
        if impact.total_affected == 0:
            return "none"

        # High: conflicts or structural issues
        if impact.conflict_count > 0:
            return "high"

        # High: 10+ tickets
        if impact.total_affected > 10:
            return "high"

        # Medium: any pending syncs
        if impact.pending_count > 0:
            return "medium"

        # Medium: 4-10 tickets (even if all synced)
        if impact.total_affected >= 4:
            return "medium"

        # Low: 1-3 synced tickets, no conflicts
        return "low"


async def analyze_and_update_op(
    op: DecisionChangeOp,
    decision: Decision,
    op_store: "DecisionChangeOpStore",
    jira_service: "JiraService",
    link_store: "DecisionLinkStore",
    decision_store: "DecisionStore",
) -> ImpactSummary:
    """Analyze impact and update the change op with results.

    Convenience function that creates an ImpactAnalysisService,
    runs analysis, and stores the result in the change operation.

    Args:
        op: The change operation to update
        decision: The decision being changed
        op_store: Store to update the operation
        jira_service: JiraService for preflight
        link_store: DecisionLinkStore for getting links
        decision_store: DecisionStore for decision lookups

    Returns:
        ImpactSummary from the analysis
    """
    service = ImpactAnalysisService(jira_service, link_store, decision_store)
    impact = await service.analyze(decision, op.operation)
    await op_store.set_impact(op.id, impact)

    logger.info(
        "Impact analysis stored on change operation",
        extra={
            "op_id": op.id,
            "decision_id": decision.id,
            "risk_level": impact.risk_level,
        },
    )

    return impact
