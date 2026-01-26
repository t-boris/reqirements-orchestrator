"""DecisionRollbackService for reverting Jira managed sections.

Phase 41-05: Rollback Support + Error Recovery

Rollback reverts Jira managed sections to a previous decision version.
Note: Database state is NOT rolled back - the decision remains at current
version. Only the Jira projection is reverted.

Use cases:
1. User regret: All updated but user wants to undo
2. Partial recovery: Restore Jira to known state after issues
3. Deprecation undo: Remove deprecation notice from Jira

ARCHITECTURE:
- Rollback only affects Jira (projection layer)
- Database state is preserved (truth layer)
- Slack messages are not changed (presentation layer)
"""
import logging
from dataclasses import dataclass
from typing import Optional

from src.db.decision_change_op_store import DecisionChangeOpStore
from src.db.decision_link_store import DecisionLinkStore
from src.db.decision_store import DecisionStore
from src.jira.client import JiraService
from src.jira.managed_sections import update_description_with_managed_section
from src.schemas.decision import (
    Decision,
    DecisionChangeOp,
    DecisionChangeOpState,
    DecisionChangeOpType,
    DecisionVersion,
)

logger = logging.getLogger(__name__)


@dataclass
class RollbackResult:
    """Result of rolling back Jira managed sections.

    Tracks per-ticket outcomes for rollback operation.
    """

    success: bool
    rolled_back_count: int = 0
    failed_count: int = 0
    error: Optional[str] = None


class DecisionRollbackService:
    """Service for rolling back Jira managed sections to previous state.

    Rollback = revert Jira managed sections to previous decision version.
    Database state is NOT changed - only Jira projection is reverted.

    ARCHITECTURE:
    - Database is truth (NOT changed by rollback)
    - Jira is projection (this is what gets rolled back)
    - Slack is presentation (NOT changed by rollback)

    This service is intentionally scoped to Jira only:
    - If user wants to undo a decision version, they need to create a new version
    - This service just restores Jira to a previous state for emergencies
    """

    def __init__(
        self,
        decision_store: DecisionStore,
        op_store: DecisionChangeOpStore,
        link_store: DecisionLinkStore,
        jira_service: JiraService,
    ):
        """Initialize rollback service with required stores.

        Args:
            decision_store: Store for decision CRUD and version history
            op_store: Store for change operation state management
            link_store: Store for decision-to-Jira links
            jira_service: Service for Jira API calls
        """
        self._decisions = decision_store
        self._ops = op_store
        self._links = link_store
        self._jira = jira_service

    async def rollback(self, op_id: str) -> RollbackResult:
        """Rollback a completed decision change operation.

        For EDIT: Reverts Jira managed sections to from_version content.
        For DEPRECATE: Removes deprecation notice, restores decision.

        Note: DB state is NOT rolled back. The decision remains at current
        version. Only Jira projection is reverted.

        Args:
            op_id: UUID of the change operation to rollback

        Returns:
            RollbackResult with per-ticket outcomes
        """
        op = await self._ops.get(op_id)
        if not op:
            return RollbackResult(success=False, error="Operation not found")

        if op.state != DecisionChangeOpState.DONE:
            return RollbackResult(
                success=False,
                error=f"Can only rollback DONE operations, got {op.state.value}"
            )

        decision = await self._decisions.get(op.decision_id)
        if not decision:
            return RollbackResult(success=False, error="Decision not found")

        # Get version history to find previous state
        history = await self._decisions.get_version_history(op.decision_id)
        prev_version = next(
            (v for v in history if v.version == op.from_version),
            None
        )

        if op.operation == DecisionChangeOpType.EDIT and prev_version:
            # Sync previous version to Jira
            return await self._rollback_edit(decision, prev_version)
        elif op.operation == DecisionChangeOpType.DEPRECATE:
            # Remove deprecation notice (but decision stays deprecated in DB)
            return await self._rollback_deprecate(decision)
        else:
            return RollbackResult(
                success=False,
                error="Cannot rollback this operation type"
            )

    async def _rollback_edit(
        self,
        decision: Decision,
        prev_version: DecisionVersion,
    ) -> RollbackResult:
        """Rollback an edit by syncing previous version to Jira.

        Creates a temporary Decision-like object from the previous version
        and syncs that to all linked Jira tickets.

        Args:
            decision: Current decision (for links lookup)
            prev_version: The previous version to restore

        Returns:
            RollbackResult with per-ticket outcomes
        """
        links = await self._links.get_links_for_decision(decision.id)
        rolled_back = 0
        failed = 0

        # Create a temporary decision with previous version content
        rollback_decision = Decision(
            id=decision.id,
            channel_id=decision.channel_id,
            decision_type=decision.decision_type,
            title=prev_version.title,
            description=prev_version.description,
            status=prev_version.status,
            version=prev_version.version,
            created_by=decision.created_by,
            created_at=decision.created_at,
            updated_at=decision.updated_at,
            canonical_message_ts=decision.canonical_message_ts,
            discussion_thread_ts=decision.discussion_thread_ts,
            # Restore rich context from version
            rationale=self._restore_rationale(prev_version.rationale),
            context=prev_version.context,
            alternatives=self._restore_alternatives(prev_version.alternatives),
            consequences=self._restore_consequences(prev_version.consequences),
        )

        for link in links:
            try:
                # Get current Jira description
                issue = await self._jira.get_issue(link.jira_key)
                current_desc = issue.description or ""

                # Get all decisions linked to this ticket (for full rebuild)
                all_links = await self._links.get_decisions_for_ticket(link.jira_key)
                all_decisions = []

                for l in all_links:
                    if l.decision_id == decision.id:
                        # Use rollback version for this decision
                        all_decisions.append(rollback_decision)
                    else:
                        # Keep other decisions at current version
                        d = await self._decisions.get(l.decision_id)
                        if d:
                            all_decisions.append(d)

                # Update managed section with previous version content
                new_desc = update_description_with_managed_section(
                    current_desc,
                    all_decisions,
                )

                await self._jira.update_issue(
                    issue_key=link.jira_key,
                    updates={"description": new_desc},
                )

                logger.info(
                    "Rolled back decision in Jira",
                    extra={
                        "decision_id": decision.id,
                        "jira_key": link.jira_key,
                        "from_version": decision.version,
                        "to_version": prev_version.version,
                    }
                )
                rolled_back += 1

            except Exception as e:
                logger.error(
                    f"Rollback failed for {link.jira_key}: {e}",
                    exc_info=True,
                )
                failed += 1

        return RollbackResult(
            success=failed == 0,
            rolled_back_count=rolled_back,
            failed_count=failed,
        )

    async def _rollback_deprecate(
        self,
        decision: Decision,
    ) -> RollbackResult:
        """Rollback a deprecation by restoring the decision in Jira.

        Note: The decision stays deprecated in DB. This only removes the
        deprecation notice from Jira and restores the decision content.

        Args:
            decision: The deprecated decision to restore in Jira

        Returns:
            RollbackResult with per-ticket outcomes
        """
        links = await self._links.get_links_for_decision(decision.id)
        rolled_back = 0
        failed = 0

        # Get the last approved version from history
        history = await self._decisions.get_version_history(decision.id)
        last_approved = None
        for v in history:
            if v.status.value == "approved":
                last_approved = v
                break

        if not last_approved:
            # No approved version found, use current decision content
            # but mark as approved for display
            restore_decision = Decision(
                id=decision.id,
                channel_id=decision.channel_id,
                decision_type=decision.decision_type,
                title=decision.title,
                description=decision.description,
                status=decision.status,  # Keep deprecated status
                version=decision.version,
                created_by=decision.created_by,
                created_at=decision.created_at,
                updated_at=decision.updated_at,
                canonical_message_ts=decision.canonical_message_ts,
                discussion_thread_ts=decision.discussion_thread_ts,
                rationale=decision.rationale,
                context=decision.context,
                alternatives=decision.alternatives,
                consequences=decision.consequences,
            )
        else:
            # Restore from last approved version
            from src.schemas.decision import DecisionStatus
            restore_decision = Decision(
                id=decision.id,
                channel_id=decision.channel_id,
                decision_type=decision.decision_type,
                title=last_approved.title,
                description=last_approved.description,
                status=DecisionStatus.APPROVED,  # Show as approved in Jira
                version=last_approved.version,
                created_by=decision.created_by,
                created_at=decision.created_at,
                updated_at=decision.updated_at,
                canonical_message_ts=decision.canonical_message_ts,
                discussion_thread_ts=decision.discussion_thread_ts,
                rationale=self._restore_rationale(last_approved.rationale),
                context=last_approved.context,
                alternatives=self._restore_alternatives(last_approved.alternatives),
                consequences=self._restore_consequences(last_approved.consequences),
            )

        for link in links:
            try:
                # Get current Jira description
                issue = await self._jira.get_issue(link.jira_key)
                current_desc = issue.description or ""

                # Get all decisions linked to this ticket
                all_links = await self._links.get_decisions_for_ticket(link.jira_key)
                all_decisions = []

                for l in all_links:
                    if l.decision_id == decision.id:
                        # Use restored version for this decision
                        all_decisions.append(restore_decision)
                    else:
                        # Keep other decisions at current version
                        d = await self._decisions.get(l.decision_id)
                        if d:
                            all_decisions.append(d)

                # Update managed section (removes deprecation notice)
                new_desc = update_description_with_managed_section(
                    current_desc,
                    all_decisions,
                )

                await self._jira.update_issue(
                    issue_key=link.jira_key,
                    updates={"description": new_desc},
                )

                logger.info(
                    "Rolled back deprecation in Jira",
                    extra={
                        "decision_id": decision.id,
                        "jira_key": link.jira_key,
                    }
                )
                rolled_back += 1

            except Exception as e:
                logger.error(
                    f"Rollback deprecation failed for {link.jira_key}: {e}",
                    exc_info=True,
                )
                failed += 1

        return RollbackResult(
            success=failed == 0,
            rolled_back_count=rolled_back,
            failed_count=failed,
        )

    def _restore_rationale(
        self,
        rationale_data: Optional[list[dict]],
    ) -> Optional[list]:
        """Convert stored rationale dicts back to RationaleItem objects."""
        if not rationale_data:
            return None
        from src.schemas.decision import RationaleItem
        return [RationaleItem(**r) for r in rationale_data]

    def _restore_alternatives(
        self,
        alternatives_data: Optional[list[dict]],
    ) -> Optional[list]:
        """Convert stored alternatives dicts back to Alternative objects."""
        if not alternatives_data:
            return None
        from src.schemas.decision import Alternative
        return [Alternative(**a) for a in alternatives_data]

    def _restore_consequences(
        self,
        consequences_data: Optional[list[dict]],
    ) -> Optional[list]:
        """Convert stored consequences dicts back to Consequence objects."""
        if not consequences_data:
            return None
        from src.schemas.decision import Consequence
        return [Consequence(**c) for c in consequences_data]
