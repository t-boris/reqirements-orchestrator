"""Preflight service for Decision -> Jira synchronization.

From CONTEXT.md:
- Every decision -> Jira update goes through Preflight
- No exceptions - decisions don't get "privileges"
- fetch Jira -> compare last_seen -> detect conflicts -> block if needed

Conflict types (same as regular preflight):
1. IDEMPOTENT - Decision already synced at this version
2. SAFE_DRIFT - Other fields changed, but our section is unchanged
3. REAL_CONFLICT - Managed section was modified externally
4. STRUCTURAL - Ticket deleted or structure changed
"""
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.db.decision_link_store import DecisionLinkStore
    from src.db.decision_store import DecisionStore
    from src.jira.client import JiraService

from src.jira.managed_sections import extract_managed_section, has_managed_section
from src.schemas.decision import Decision, DecisionLink
from src.sync.preflight import ConflictType, FieldChange

logger = logging.getLogger(__name__)


@dataclass
class DecisionPreflightResult:
    """Result of decision preflight check."""

    conflict_type: ConflictType
    decision: Optional[Decision]
    jira_key: str
    link: Optional[DecisionLink]
    detected_changes: list[FieldChange]
    message: str
    can_proceed: bool  # True for IDEMPOTENT
    needs_choice: bool  # True for SAFE_DRIFT, REAL_CONFLICT, STRUCTURAL


class DecisionPreflightService:
    """Preflight checks for decision -> Jira synchronization.

    Every sync goes through preflight. No exceptions.
    """

    def __init__(
        self,
        jira_service: "JiraService",
        decision_store: "DecisionStore",
        link_store: "DecisionLinkStore",
    ):
        self._jira = jira_service
        self._decisions = decision_store
        self._links = link_store

    async def check_sync(
        self,
        decision_id: str,
        jira_key: str,
    ) -> DecisionPreflightResult:
        """Check if decision can be synced to Jira ticket.

        Steps:
        1. Get decision and link
        2. Fetch current Jira description
        3. Check if managed section was modified externally
        4. Classify conflict type

        Args:
            decision_id: Decision UUID
            jira_key: Target Jira ticket key

        Returns:
            DecisionPreflightResult with conflict classification
        """
        # Get decision
        decision = await self._decisions.get(decision_id)
        if not decision:
            return DecisionPreflightResult(
                conflict_type=ConflictType.STRUCTURAL,
                decision=None,
                jira_key=jira_key,
                link=None,
                detected_changes=[],
                message="Decision not found",
                can_proceed=False,
                needs_choice=True,
            )

        # Get link
        link = await self._links.get_link(decision_id, jira_key)
        if not link:
            # No link yet - this is a new sync, no conflict
            return DecisionPreflightResult(
                conflict_type=ConflictType.SAFE_DRIFT,  # Treat as safe
                decision=decision,
                jira_key=jira_key,
                link=None,
                detected_changes=[],
                message="New link, no prior sync",
                can_proceed=True,
                needs_choice=False,
            )

        # Check if already synced at current version
        if link.synced_version and link.synced_version >= decision.version:
            return DecisionPreflightResult(
                conflict_type=ConflictType.IDEMPOTENT,
                decision=decision,
                jira_key=jira_key,
                link=link,
                detected_changes=[],
                message=f"Already synced at v{link.synced_version}",
                can_proceed=True,
                needs_choice=False,
            )

        # Fetch current Jira state
        try:
            issue = await self._jira.get_issue(jira_key)
        except Exception as e:
            return DecisionPreflightResult(
                conflict_type=ConflictType.STRUCTURAL,
                decision=decision,
                jira_key=jira_key,
                link=link,
                detected_changes=[],
                message=f"Issue not found or error: {e}",
                can_proceed=False,
                needs_choice=True,
            )

        # Check managed section
        description = issue.description or ""
        managed_section = extract_managed_section(description)

        if managed_section:
            # Section exists - check if it was modified externally
            # For now, simple approach: if section exists and we haven't synced, it's a conflict
            # TODO: More sophisticated fingerprinting
            if link.synced_version is None:
                return DecisionPreflightResult(
                    conflict_type=ConflictType.REAL_CONFLICT,
                    decision=decision,
                    jira_key=jira_key,
                    link=link,
                    detected_changes=[
                        FieldChange(
                            field="description.managed_section",
                            local_value=None,
                            jira_value=managed_section.content,
                            changed_by=None,
                            changed_at=None,
                        )
                    ],
                    message="Managed section exists but was never synced",
                    can_proceed=False,
                    needs_choice=True,
                )

        # Safe to proceed
        return DecisionPreflightResult(
            conflict_type=ConflictType.SAFE_DRIFT,
            decision=decision,
            jira_key=jira_key,
            link=link,
            detected_changes=[],
            message="Safe to sync",
            can_proceed=True,
            needs_choice=False,
        )

    async def check_batch_sync(
        self,
        decision: Decision,
    ) -> list[DecisionPreflightResult]:
        """Check preflight for all linked tickets of a decision.

        Returns list of preflight results, one per linked ticket.
        """
        links = await self._links.get_links_for_decision(decision.id)
        results = []

        for link in links:
            result = await self.check_sync(decision.id, link.jira_key)
            results.append(result)

        return results
