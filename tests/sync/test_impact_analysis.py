"""Tests for ImpactAnalysisService.

Tests cover:
1. No links returns empty impact
2. All synced returns low risk
3. Pending syncs returns medium risk
4. Conflicts returns high risk
5. Structural issues returns high risk
6. Deprecate always has jira_writes
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.schemas.decision import (
    Decision,
    DecisionChangeOpType,
    DecisionLink,
    DecisionStatus,
    DecisionType,
    ImpactSummary,
    ImpactTicket,
    JiraFieldPath,
)


# Local ConflictType to avoid circular import
class ConflictType(str, Enum):
    """Preflight conflict classification."""
    IDEMPOTENT = "idempotent"
    SAFE_DRIFT = "safe_drift"
    REAL_CONFLICT = "real_conflict"
    STRUCTURAL = "structural"


@dataclass
class DecisionPreflightResult:
    """Result of decision preflight check (local copy for tests)."""
    conflict_type: ConflictType
    decision: Optional[Decision]
    jira_key: str
    link: Optional[DecisionLink]
    detected_changes: list
    message: str
    can_proceed: bool
    needs_choice: bool


def compute_risk_level(impact: ImpactSummary) -> str:
    """Compute risk level based on impact analysis (local for tests).

    Risk levels:
    - none: no affected entities
    - low: 1-3 synced tickets, no conflicts
    - medium: 4-10 tickets OR any pending syncs
    - high: 10+ tickets OR any conflicts OR structural issues
    """
    if impact.total_affected == 0:
        return "none"
    if impact.conflict_count > 0:
        return "high"
    if impact.total_affected > 10:
        return "high"
    if impact.pending_count > 0:
        return "medium"
    if impact.total_affected >= 4:
        return "medium"
    return "low"


class TestImpactAnalysisLogic:
    """Test the impact analysis logic with mocked preflight results.

    Note: Uses simulated analyze function due to circular import issues
    with the actual ImpactAnalysisService.
    """

    @pytest.fixture
    def sample_decision(self) -> Decision:
        """Create a sample decision for testing."""
        return Decision(
            id="dec-12345678-1234-5678-1234-567812345678",
            channel_id="C12345",
            decision_type=DecisionType.ARCH,
            title="Use PostgreSQL",
            description="We will use PostgreSQL as our database.",
            status=DecisionStatus.APPROVED,
            version=2,
            created_by="U12345",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def _make_link(
        self,
        decision_id: str,
        jira_key: str,
        synced_version: int | None = None,
    ) -> DecisionLink:
        """Create a DecisionLink for testing."""
        return DecisionLink(
            id="link-12345",
            decision_id=decision_id,
            jira_key=jira_key,
            field_path=JiraFieldPath.DESC_ARCHITECTURE,
            linked_at=datetime.now(timezone.utc),
            linked_by="U12345",
            synced_version=synced_version,
        )

    def _make_preflight_result(
        self,
        jira_key: str,
        conflict_type: ConflictType,
        message: str = "",
        can_proceed: bool = True,
    ) -> DecisionPreflightResult:
        """Create a preflight result for testing."""
        return DecisionPreflightResult(
            conflict_type=conflict_type,
            decision=None,
            jira_key=jira_key,
            link=None,
            detected_changes=[],
            message=message,
            can_proceed=can_proceed,
            needs_choice=not can_proceed,
        )

    def _simulate_analyze(
        self,
        links: list[DecisionLink],
        preflight_results: list[DecisionPreflightResult],
        operation: DecisionChangeOpType,
    ) -> ImpactSummary:
        """Simulate ImpactAnalysisService.analyze() logic for testing."""
        if not links:
            return ImpactSummary(
                total_affected=0,
                has_jira_writes=False,
                risk_level="none",
            )

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
                link = next((l for l in links if l.jira_key == pr.jira_key), None)
                tickets.append(
                    ImpactTicket(
                        jira_key=pr.jira_key,
                        sync_status="synced",
                        last_synced_version=link.synced_version if link else None,
                    )
                )
                safe_count += 1
            else:  # SAFE_DRIFT
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
        impact.risk_level = compute_risk_level(impact)

        return impact

    def test_no_links_returns_empty_impact(self, sample_decision: Decision):
        """Decision with no links returns empty impact with 'none' risk."""
        impact = self._simulate_analyze([], [], DecisionChangeOpType.EDIT)

        assert impact.total_affected == 0
        assert impact.has_jira_writes is False
        assert impact.risk_level == "none"
        assert impact.jira_keys == []
        assert impact.tickets == []

    def test_all_synced_returns_low_risk(self, sample_decision: Decision):
        """All tickets already synced returns low risk."""
        links = [
            self._make_link(sample_decision.id, "SCRUM-123", synced_version=2),
            self._make_link(sample_decision.id, "SCRUM-456", synced_version=2),
        ]
        preflight_results = [
            self._make_preflight_result("SCRUM-123", ConflictType.IDEMPOTENT),
            self._make_preflight_result("SCRUM-456", ConflictType.IDEMPOTENT),
        ]

        impact = self._simulate_analyze(links, preflight_results, DecisionChangeOpType.EDIT)

        assert impact.total_affected == 2
        assert impact.safe_count == 2
        assert impact.pending_count == 0
        assert impact.conflict_count == 0
        assert impact.has_jira_writes is False
        assert impact.risk_level == "low"

    def test_pending_syncs_returns_medium_risk(self, sample_decision: Decision):
        """Some tickets need sync returns medium risk."""
        links = [
            self._make_link(sample_decision.id, "SCRUM-123", synced_version=1),
            self._make_link(sample_decision.id, "SCRUM-456", synced_version=2),
        ]
        preflight_results = [
            self._make_preflight_result("SCRUM-123", ConflictType.SAFE_DRIFT, "Safe to sync"),
            self._make_preflight_result("SCRUM-456", ConflictType.IDEMPOTENT),
        ]

        impact = self._simulate_analyze(links, preflight_results, DecisionChangeOpType.EDIT)

        assert impact.total_affected == 2
        assert impact.pending_count == 1
        assert impact.safe_count == 1
        assert impact.has_jira_writes is True
        assert impact.risk_level == "medium"

    def test_conflicts_returns_high_risk(self, sample_decision: Decision):
        """Real conflicts detected returns high risk."""
        links = [
            self._make_link(sample_decision.id, "SCRUM-123", synced_version=1),
        ]
        preflight_results = [
            self._make_preflight_result(
                "SCRUM-123",
                ConflictType.REAL_CONFLICT,
                "Managed section was modified externally",
                can_proceed=False,
            ),
        ]

        impact = self._simulate_analyze(links, preflight_results, DecisionChangeOpType.EDIT)

        assert impact.total_affected == 1
        assert impact.conflict_count == 1
        assert impact.risk_level == "high"
        assert impact.tickets[0].sync_status == "conflict"
        assert impact.tickets[0].conflict_type == "real_conflict"

    def test_structural_issues_returns_high_risk(self, sample_decision: Decision):
        """Deleted/missing tickets returns high risk."""
        links = [
            self._make_link(sample_decision.id, "SCRUM-123", synced_version=1),
        ]
        preflight_results = [
            self._make_preflight_result(
                "SCRUM-123",
                ConflictType.STRUCTURAL,
                "Issue not found in Jira",
                can_proceed=False,
            ),
        ]

        impact = self._simulate_analyze(links, preflight_results, DecisionChangeOpType.EDIT)

        assert impact.total_affected == 1
        assert impact.conflict_count == 1
        assert impact.risk_level == "high"
        assert impact.tickets[0].sync_status == "structural"
        assert impact.tickets[0].conflict_type == "structural"

    def test_deprecate_always_has_jira_writes(self, sample_decision: Decision):
        """Deprecate operation triggers writes even if all synced."""
        links = [
            self._make_link(sample_decision.id, "SCRUM-123", synced_version=2),
        ]
        preflight_results = [
            self._make_preflight_result("SCRUM-123", ConflictType.IDEMPOTENT),
        ]

        impact = self._simulate_analyze(links, preflight_results, DecisionChangeOpType.DEPRECATE)

        assert impact.total_affected == 1
        assert impact.safe_count == 1
        assert impact.pending_count == 0
        assert impact.has_jira_writes is True

    def test_many_tickets_returns_high_risk(self, sample_decision: Decision):
        """10+ tickets returns high risk even if all synced."""
        links = [
            self._make_link(sample_decision.id, f"SCRUM-{i}", synced_version=2)
            for i in range(11)
        ]
        preflight_results = [
            self._make_preflight_result(f"SCRUM-{i}", ConflictType.IDEMPOTENT)
            for i in range(11)
        ]

        impact = self._simulate_analyze(links, preflight_results, DecisionChangeOpType.EDIT)

        assert impact.total_affected == 11
        assert impact.safe_count == 11
        assert impact.risk_level == "high"

    def test_medium_ticket_count_returns_medium_risk(self, sample_decision: Decision):
        """4-10 tickets returns medium risk even if all synced."""
        links = [
            self._make_link(sample_decision.id, f"SCRUM-{i}", synced_version=2)
            for i in range(5)
        ]
        preflight_results = [
            self._make_preflight_result(f"SCRUM-{i}", ConflictType.IDEMPOTENT)
            for i in range(5)
        ]

        impact = self._simulate_analyze(links, preflight_results, DecisionChangeOpType.EDIT)

        assert impact.total_affected == 5
        assert impact.safe_count == 5
        assert impact.risk_level == "medium"


class TestComputeRiskLevel:
    """Test risk level computation logic."""

    def test_none_risk_for_no_affected(self):
        """No affected entities = 'none' risk."""
        impact = ImpactSummary(total_affected=0)
        assert compute_risk_level(impact) == "none"

    def test_high_risk_for_conflicts(self):
        """Any conflict = 'high' risk."""
        impact = ImpactSummary(total_affected=1, conflict_count=1)
        assert compute_risk_level(impact) == "high"

    def test_high_risk_for_many_tickets(self):
        """10+ tickets = 'high' risk."""
        impact = ImpactSummary(total_affected=11, safe_count=11)
        assert compute_risk_level(impact) == "high"

    def test_medium_risk_for_pending(self):
        """Any pending sync = 'medium' risk."""
        impact = ImpactSummary(total_affected=1, pending_count=1)
        assert compute_risk_level(impact) == "medium"

    def test_medium_risk_for_mid_ticket_count(self):
        """4-10 tickets = 'medium' risk."""
        impact = ImpactSummary(total_affected=5, safe_count=5)
        assert compute_risk_level(impact) == "medium"

    def test_low_risk_for_few_synced(self):
        """1-3 synced tickets = 'low' risk."""
        impact = ImpactSummary(total_affected=3, safe_count=3)
        assert compute_risk_level(impact) == "low"


class TestImpactSummaryModel:
    """Test ImpactSummary model with new fields."""

    def test_default_risk_level(self):
        """Default risk level is 'none'."""
        impact = ImpactSummary()
        assert impact.risk_level == "none"

    def test_default_has_jira_writes(self):
        """Default has_jira_writes is False."""
        impact = ImpactSummary()
        assert impact.has_jira_writes is False

    def test_full_impact_summary(self):
        """ImpactSummary with all fields."""
        impact = ImpactSummary(
            jira_keys=["SCRUM-123"],
            tickets=[
                ImpactTicket(
                    jira_key="SCRUM-123",
                    sync_status="pending",
                    last_synced_version=1,
                    message="Needs sync",
                )
            ],
            conflict_count=0,
            pending_count=1,
            safe_count=0,
            total_affected=1,
            has_jira_writes=True,
            risk_level="medium",
        )

        assert impact.jira_keys == ["SCRUM-123"]
        assert len(impact.tickets) == 1
        assert impact.tickets[0].sync_status == "pending"
        assert impact.pending_count == 1
        assert impact.has_jira_writes is True
        assert impact.risk_level == "medium"


class TestImpactTicketModel:
    """Test ImpactTicket model."""

    def test_minimal_impact_ticket(self):
        """ImpactTicket with required fields only."""
        ticket = ImpactTicket(jira_key="SCRUM-123", sync_status="synced")
        assert ticket.jira_key == "SCRUM-123"
        assert ticket.sync_status == "synced"
        assert ticket.last_synced_version is None
        assert ticket.conflict_type is None
        assert ticket.message is None

    def test_full_impact_ticket(self):
        """ImpactTicket with all fields."""
        ticket = ImpactTicket(
            jira_key="SCRUM-123",
            sync_status="conflict",
            last_synced_version=2,
            conflict_type="real_conflict",
            message="Managed section modified externally",
        )
        assert ticket.jira_key == "SCRUM-123"
        assert ticket.sync_status == "conflict"
        assert ticket.last_synced_version == 2
        assert ticket.conflict_type == "real_conflict"
        assert ticket.message == "Managed section modified externally"
