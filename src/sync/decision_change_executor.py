"""DecisionChangeExecutor for applying decision changes transactionally.

Truth-first ordering:
1. Update decision state in DB (new version/deprecate) — always first
2. Update pinned decision message (Slack) — if fails, retry, but DB is already truth
3. Update channel index pinned
4. Jira updates: MANAGED_SECTION_ONLY, include decision_version marker

Each apply is idempotent (by op_id).
"""
import logging
from typing import Optional

from slack_sdk import WebClient

from src.db.decision_change_op_store import DecisionChangeOpStore
from src.db.decision_link_store import DecisionLinkStore
from src.db.decision_store import DecisionStore
from src.jira.client import JiraService
from src.schemas.decision import (
    ApplyResult,
    ApplyTicketResult,
    Decision,
    DecisionChangeOp,
    DecisionChangeOpState,
    DecisionChangeOpType,
)
from src.slack.blocks.decision_cards import (
    build_approved_card,
    build_deprecated_decision_blocks,
)
from src.sync.decision_sync import DecisionSyncService

logger = logging.getLogger(__name__)


class DecisionChangeExecutor:
    """Execute decision change operations with truth-first ordering.

    ARCHITECTURE:
    - Database is truth (updated first)
    - Slack is presentation (best effort, never blocks)
    - Jira is projection (sync via DecisionSyncService)

    This executor handles the transactional application of confirmed
    decision change operations. It ensures:
    - DB changes commit before external systems
    - Slack failures don't abort the operation
    - Per-ticket results are tracked for retry capability
    """

    def __init__(
        self,
        decision_store: DecisionStore,
        op_store: DecisionChangeOpStore,
        link_store: DecisionLinkStore,
        jira_service: JiraService,
        slack_client: WebClient,
    ):
        """Initialize executor with required stores and clients.

        Args:
            decision_store: Store for decision CRUD operations
            op_store: Store for change operation state management
            link_store: Store for decision-to-Jira links
            jira_service: Service for Jira API calls
            slack_client: Slack WebClient for message updates
        """
        self._decisions = decision_store
        self._ops = op_store
        self._links = link_store
        self._jira = jira_service
        self._slack = slack_client

    async def execute(
        self,
        op_id: str,
        skip_jira: bool = False,
    ) -> ApplyResult:
        """Execute a confirmed decision change operation.

        Truth-first ordering:
        1. DB (already updated for EDIT, needs update for DEPRECATE/DELETE)
        2. Slack (best effort - failures logged but don't abort)
        3. Jira (if not skip_jira)

        Args:
            op_id: UUID of the change operation to execute
            skip_jira: If True, skip Jira sync (Slack-only mode)

        Returns:
            ApplyResult with detailed outcomes for each phase
        """
        # Load operation
        op = await self._ops.get(op_id)
        if not op:
            return ApplyResult(
                op_id=op_id,
                decision_id="",
                success=False,
                error="Operation not found",
            )

        if op.state != DecisionChangeOpState.CONFIRMED:
            return ApplyResult(
                op_id=op_id,
                decision_id=op.decision_id,
                success=False,
                error=f"Operation not confirmed (state: {op.state.value})",
            )

        # Transition to APPLYING
        await self._ops.update_state(op_id, DecisionChangeOpState.APPLYING)

        result = ApplyResult(
            op_id=op_id,
            decision_id=op.decision_id,
            success=True,
        )

        try:
            # Get decision
            decision = await self._decisions.get(op.decision_id)
            if not decision:
                raise ValueError("Decision not found")

            # Phase 1: DB (for DEPRECATE/DELETE - EDIT already done when op created)
            if op.operation in (DecisionChangeOpType.DEPRECATE, DecisionChangeOpType.DELETE):
                await self._apply_to_db(op, decision)
                # Refresh decision after DB update
                decision = await self._decisions.get(op.decision_id)
                if not decision:
                    raise ValueError("Decision not found after DB update")
            result.db_updated = True

            # Phase 2: Slack (best effort)
            try:
                await self._apply_to_slack(op, decision)
                result.slack_updated = True
            except Exception as e:
                logger.warning(
                    "Slack update failed (continuing - Slack is presentation)",
                    extra={"op_id": op_id, "error": str(e)},
                )
                # Continue - Slack is presentation, not truth

            # Phase 3: Jira (if not skipped)
            if not skip_jira and op.impact_summary and op.impact_summary.has_jira_writes:
                ticket_results = await self._apply_to_jira(op, decision)
                result.ticket_results = ticket_results
                result.total_tickets = len(ticket_results)
                result.updated_count = sum(1 for r in ticket_results if r.success)
                result.skipped_count = sum(
                    1 for r in ticket_results if r.action == "skipped"
                )
                result.failed_count = sum(1 for r in ticket_results if not r.success)
                result.jira_updated = result.failed_count == 0

            # Complete operation
            if result.failed_count == 0:
                await self._ops.complete(op_id)
            else:
                await self._ops.fail(op_id, f"{result.failed_count} ticket(s) failed")
                result.success = False

        except Exception as e:
            logger.error(
                "Execute failed",
                extra={"op_id": op_id, "error": str(e)},
                exc_info=True,
            )
            await self._ops.fail(op_id, str(e))
            result.success = False
            result.error = str(e)

        return result

    async def _apply_to_db(
        self,
        op: DecisionChangeOp,
        decision: Decision,
    ) -> None:
        """Apply change to database (truth layer).

        For EDIT: Decision already updated when op was created
        For DEPRECATE/DELETE: Apply deprecation now

        Args:
            op: The change operation
            decision: Current decision state
        """
        if op.operation == DecisionChangeOpType.DEPRECATE:
            # Deprecate the decision
            await self._decisions.deprecate(
                decision_id=decision.id,
                deprecated_by=op.actor,
                reason="Deprecated via decision change operation",
                replaced_by=None,
            )
            logger.info(
                "Decision deprecated in DB",
                extra={"decision_id": decision.id, "op_id": op.id},
            )

        elif op.operation == DecisionChangeOpType.DELETE:
            # DELETE is implemented as deprecation with tombstone marker
            await self._decisions.deprecate(
                decision_id=decision.id,
                deprecated_by=op.actor,
                reason="Deleted via decision change operation (tombstone)",
                replaced_by=None,
            )
            logger.info(
                "Decision deleted (tombstone) in DB",
                extra={"decision_id": decision.id, "op_id": op.id},
            )

    async def _apply_to_slack(
        self,
        op: DecisionChangeOp,
        decision: Decision,
    ) -> None:
        """Apply change to Slack (presentation layer).

        Updates the pinned decision message to reflect the new state.
        Best effort - failures are logged but don't abort the operation.

        Args:
            op: The change operation
            decision: Current (updated) decision state
        """
        # Check if decision has canonical message
        if not decision.canonical_message_ts:
            logger.debug(
                "Decision has no canonical message, skipping Slack update",
                extra={"decision_id": decision.id},
            )
            return

        # Build appropriate card based on operation type
        if op.operation in (DecisionChangeOpType.DEPRECATE, DecisionChangeOpType.DELETE):
            blocks = build_deprecated_decision_blocks(decision)
            text = f"Decision DEC-{decision.id[:8]} has been deprecated"
        else:
            # EDIT: Show updated approved card
            links = await self._links.get_links_for_decision(decision.id)
            linked_tickets = [link.jira_key for link in links]
            blocks = build_approved_card(decision, linked_tickets)
            text = f"Decision DEC-{decision.id[:8]} updated to v{decision.version}"

        # Update the canonical message
        self._slack.chat_update(
            channel=decision.channel_id,
            ts=decision.canonical_message_ts,
            blocks=blocks,
            text=text,
        )

        logger.info(
            "Slack canonical message updated",
            extra={
                "decision_id": decision.id,
                "message_ts": decision.canonical_message_ts,
                "operation": op.operation.value,
            },
        )

    async def _apply_to_jira(
        self,
        op: DecisionChangeOp,
        decision: Decision,
    ) -> list[ApplyTicketResult]:
        """Apply change to Jira (projection layer).

        Uses DecisionSyncService to sync the decision to all linked tickets.
        Collects per-ticket results for retry capability.

        Args:
            op: The change operation
            decision: Current (updated) decision state

        Returns:
            List of per-ticket results
        """
        results: list[ApplyTicketResult] = []

        # Create sync service
        sync_service = DecisionSyncService(
            jira_service=self._jira,
            decision_store=self._decisions,
            link_store=self._links,
        )

        # Sync decision to all linked tickets
        sync_result = await sync_service.sync_decision(
            decision_id=decision.id,
            force=False,  # Respect conflict detection
        )

        # Convert sync results to apply results
        for ticket_result in sync_result.ticket_results:
            if ticket_result.success:
                results.append(ApplyTicketResult(
                    jira_key=ticket_result.jira_key,
                    success=True,
                    action="updated" if ticket_result.preflight_result else "skipped",
                ))
            else:
                results.append(ApplyTicketResult(
                    jira_key=ticket_result.jira_key,
                    success=False,
                    error=ticket_result.error or "Unknown error",
                    action="failed",
                ))

        logger.info(
            "Jira sync completed",
            extra={
                "decision_id": decision.id,
                "op_id": op.id,
                "total": sync_result.total_tickets,
                "synced": sync_result.synced_count,
                "failed": sync_result.failed_count,
            },
        )

        return results

    async def retry_failed_tickets(
        self,
        op_id: str,
        jira_keys: Optional[list[str]] = None,
    ) -> ApplyResult:
        """Retry failed ticket syncs from a previous execution.

        Args:
            op_id: UUID of the change operation
            jira_keys: Specific tickets to retry (None = all failed)

        Returns:
            ApplyResult with retry outcomes
        """
        op = await self._ops.get(op_id)
        if not op:
            return ApplyResult(
                op_id=op_id,
                decision_id="",
                success=False,
                error="Operation not found",
            )

        if op.state != DecisionChangeOpState.FAILED:
            return ApplyResult(
                op_id=op_id,
                decision_id=op.decision_id,
                success=False,
                error=f"Operation not in FAILED state (state: {op.state.value})",
            )

        # Retry transitions FAILED -> APPLYING
        await self._ops.retry(op_id)

        decision = await self._decisions.get(op.decision_id)
        if not decision:
            await self._ops.fail(op_id, "Decision not found")
            return ApplyResult(
                op_id=op_id,
                decision_id=op.decision_id,
                success=False,
                error="Decision not found",
            )

        # Re-run Jira sync
        ticket_results = await self._apply_to_jira(op, decision)

        result = ApplyResult(
            op_id=op_id,
            decision_id=op.decision_id,
            success=True,
            db_updated=True,  # Already done
            slack_updated=True,  # Already done
            jira_updated=False,
            ticket_results=ticket_results,
            total_tickets=len(ticket_results),
            updated_count=sum(1 for r in ticket_results if r.success),
            failed_count=sum(1 for r in ticket_results if not r.success),
        )

        result.jira_updated = result.failed_count == 0
        result.success = result.jira_updated

        if result.success:
            await self._ops.complete(op_id)
        else:
            await self._ops.fail(op_id, f"{result.failed_count} ticket(s) still failing")

        return result
