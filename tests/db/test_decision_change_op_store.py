"""Tests for DecisionChangeOpStore operations."""
import pytest

from src.db.decision_change_op_store import (
    DecisionChangeOpStore,
    validate_transition,
    VALID_TRANSITIONS,
)
from src.schemas.decision import (
    DecisionChangeOpState,
    DecisionChangeOpType,
    ImpactSummary,
)


class TestValidateTransition:
    """Test state machine validation."""

    def test_valid_proposed_to_confirmed(self):
        """PROPOSED → CONFIRMED is valid."""
        validate_transition(
            DecisionChangeOpState.PROPOSED,
            DecisionChangeOpState.CONFIRMED,
        )  # Should not raise

    def test_valid_proposed_to_cancelled(self):
        """PROPOSED → CANCELLED is valid."""
        validate_transition(
            DecisionChangeOpState.PROPOSED,
            DecisionChangeOpState.CANCELLED,
        )

    def test_valid_confirmed_to_applying(self):
        """CONFIRMED → APPLYING is valid."""
        validate_transition(
            DecisionChangeOpState.CONFIRMED,
            DecisionChangeOpState.APPLYING,
        )

    def test_valid_applying_to_done(self):
        """APPLYING → DONE is valid."""
        validate_transition(
            DecisionChangeOpState.APPLYING,
            DecisionChangeOpState.DONE,
        )

    def test_valid_applying_to_failed(self):
        """APPLYING → FAILED is valid."""
        validate_transition(
            DecisionChangeOpState.APPLYING,
            DecisionChangeOpState.FAILED,
        )

    def test_valid_failed_to_applying_retry(self):
        """FAILED → APPLYING (retry) is valid."""
        validate_transition(
            DecisionChangeOpState.FAILED,
            DecisionChangeOpState.APPLYING,
        )

    def test_valid_failed_to_cancelled(self):
        """FAILED → CANCELLED is valid."""
        validate_transition(
            DecisionChangeOpState.FAILED,
            DecisionChangeOpState.CANCELLED,
        )

    def test_invalid_proposed_to_done(self):
        """PROPOSED → DONE is invalid (must go through CONFIRMED and APPLYING)."""
        with pytest.raises(ValueError, match="Invalid state transition"):
            validate_transition(
                DecisionChangeOpState.PROPOSED,
                DecisionChangeOpState.DONE,
            )

    def test_invalid_done_to_anything(self):
        """DONE is terminal - no transitions allowed."""
        with pytest.raises(ValueError, match="Invalid state transition"):
            validate_transition(
                DecisionChangeOpState.DONE,
                DecisionChangeOpState.PROPOSED,
            )

    def test_invalid_cancelled_to_anything(self):
        """CANCELLED is terminal - no transitions allowed."""
        with pytest.raises(ValueError, match="Invalid state transition"):
            validate_transition(
                DecisionChangeOpState.CANCELLED,
                DecisionChangeOpState.PROPOSED,
            )

    def test_all_states_covered(self):
        """All DecisionChangeOpState values are in VALID_TRANSITIONS."""
        for state in DecisionChangeOpState:
            assert state in VALID_TRANSITIONS


class TestDecisionChangeOpStore:
    """Test suite for DecisionChangeOpStore."""

    @pytest.fixture
    async def store(self, db_connection):
        """Create store with test connection."""
        store = DecisionChangeOpStore(db_connection)
        await store.create_tables()
        return store

    @pytest.fixture
    def decision_id(self):
        """Fixture decision ID."""
        return "dec-12345678-1234-5678-1234-567812345678"

    @pytest.mark.asyncio
    async def test_create_edit_operation(self, store, decision_id):
        """create() creates EDIT operation in PROPOSED state."""
        op = await store.create(
            decision_id=decision_id,
            operation=DecisionChangeOpType.EDIT,
            from_version=1,
            to_version=2,
            actor="U12345",
        )

        assert op.id is not None
        assert op.decision_id == decision_id
        assert op.operation == DecisionChangeOpType.EDIT
        assert op.from_version == 1
        assert op.to_version == 2
        assert op.actor == "U12345"
        assert op.state == DecisionChangeOpState.PROPOSED
        assert op.created_at is not None
        assert op.confirmed_at is None
        assert op.completed_at is None
        assert op.impact_summary is None
        assert op.error_details is None

    @pytest.mark.asyncio
    async def test_create_deprecate_operation(self, store, decision_id):
        """create() creates DEPRECATE operation with None to_version."""
        op = await store.create(
            decision_id=decision_id,
            operation=DecisionChangeOpType.DEPRECATE,
            from_version=3,
            to_version=None,
            actor="U12345",
        )

        assert op.operation == DecisionChangeOpType.DEPRECATE
        assert op.from_version == 3
        assert op.to_version is None

    @pytest.mark.asyncio
    async def test_get_operation(self, store, decision_id):
        """get() retrieves operation by ID."""
        created = await store.create(
            decision_id=decision_id,
            operation=DecisionChangeOpType.EDIT,
            from_version=1,
            to_version=2,
            actor="U12345",
        )

        retrieved = await store.get(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.decision_id == decision_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store):
        """get() returns None for nonexistent ID."""
        result = await store.get("nonexistent-uuid")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_for_decision(self, store, decision_id):
        """get_for_decision() returns ops for a decision."""
        await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.create(decision_id, DecisionChangeOpType.EDIT, 2, 3, "U2")
        await store.create("other-decision", DecisionChangeOpType.EDIT, 1, 2, "U3")

        results = await store.get_for_decision(decision_id)

        assert len(results) == 2
        # Newest first
        assert results[0].from_version == 2
        assert results[1].from_version == 1

    @pytest.mark.asyncio
    async def test_get_for_decision_with_state_filter(self, store, decision_id):
        """get_for_decision() filters by state."""
        op1 = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.create(decision_id, DecisionChangeOpType.EDIT, 2, 3, "U2")
        await store.confirm(op1.id)

        results = await store.get_for_decision(
            decision_id, state=DecisionChangeOpState.CONFIRMED
        )

        assert len(results) == 1
        assert results[0].state == DecisionChangeOpState.CONFIRMED

    @pytest.mark.asyncio
    async def test_confirm_operation(self, store, decision_id):
        """confirm() transitions PROPOSED → CONFIRMED."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")

        confirmed = await store.confirm(op.id)

        assert confirmed.state == DecisionChangeOpState.CONFIRMED
        assert confirmed.confirmed_at is not None
        assert confirmed.completed_at is None

    @pytest.mark.asyncio
    async def test_confirm_invalid_state_raises(self, store, decision_id):
        """confirm() raises for non-PROPOSED state."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.confirm(op.id)  # Now CONFIRMED

        with pytest.raises(ValueError, match="Invalid state transition"):
            await store.confirm(op.id)  # Can't confirm again

    @pytest.mark.asyncio
    async def test_cancel_from_proposed(self, store, decision_id):
        """cancel() works from PROPOSED state."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")

        cancelled = await store.cancel(op.id)

        assert cancelled.state == DecisionChangeOpState.CANCELLED
        assert cancelled.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_from_failed(self, store, decision_id):
        """cancel() works from FAILED state."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.confirm(op.id)
        await store.start_applying(op.id)
        await store.fail(op.id, "Something went wrong")

        cancelled = await store.cancel(op.id)

        assert cancelled.state == DecisionChangeOpState.CANCELLED

    @pytest.mark.asyncio
    async def test_complete_operation(self, store, decision_id):
        """complete() transitions APPLYING → DONE."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.confirm(op.id)
        await store.start_applying(op.id)

        completed = await store.complete(op.id)

        assert completed.state == DecisionChangeOpState.DONE
        assert completed.completed_at is not None

    @pytest.mark.asyncio
    async def test_fail_operation(self, store, decision_id):
        """fail() transitions APPLYING → FAILED with error details."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.confirm(op.id)
        await store.start_applying(op.id)

        failed = await store.fail(op.id, "Jira API error: 503")

        assert failed.state == DecisionChangeOpState.FAILED
        assert failed.error_details == "Jira API error: 503"
        assert failed.completed_at is not None

    @pytest.mark.asyncio
    async def test_retry_operation(self, store, decision_id):
        """retry() transitions FAILED → APPLYING."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.confirm(op.id)
        await store.start_applying(op.id)
        await store.fail(op.id, "Transient error")

        retried = await store.retry(op.id)

        assert retried.state == DecisionChangeOpState.APPLYING

    @pytest.mark.asyncio
    async def test_set_impact(self, store, decision_id):
        """set_impact() stores impact summary."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")

        impact = ImpactSummary(
            jira_keys=["SCRUM-123", "SCRUM-456"],
            pinned_artifacts=["1234.5678"],
            conflict_count=1,
            total_affected=3,
        )

        updated = await store.set_impact(op.id, impact)

        assert updated.impact_summary is not None
        assert updated.impact_summary.jira_keys == ["SCRUM-123", "SCRUM-456"]
        assert updated.impact_summary.pinned_artifacts == ["1234.5678"]
        assert updated.impact_summary.conflict_count == 1
        assert updated.impact_summary.total_affected == 3

    @pytest.mark.asyncio
    async def test_get_pending_for_decision(self, store, decision_id):
        """get_pending_for_decision() returns most recent non-terminal op."""
        op1 = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.confirm(op1.id)
        await store.start_applying(op1.id)
        await store.complete(op1.id)  # Terminal

        op2 = await store.create(decision_id, DecisionChangeOpType.EDIT, 2, 3, "U1")

        pending = await store.get_pending_for_decision(decision_id)

        assert pending is not None
        assert pending.id == op2.id

    @pytest.mark.asyncio
    async def test_get_pending_for_decision_none(self, store, decision_id):
        """get_pending_for_decision() returns None when all ops terminal."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.cancel(op.id)

        pending = await store.get_pending_for_decision(decision_id)

        assert pending is None

    @pytest.mark.asyncio
    async def test_full_lifecycle_success(self, store, decision_id):
        """Complete successful lifecycle: PROPOSED → CONFIRMED → APPLYING → DONE."""
        # Create
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        assert op.state == DecisionChangeOpState.PROPOSED

        # Set impact
        impact = ImpactSummary(jira_keys=["SCRUM-123"], total_affected=1)
        op = await store.set_impact(op.id, impact)
        assert op.impact_summary is not None

        # Confirm
        op = await store.confirm(op.id)
        assert op.state == DecisionChangeOpState.CONFIRMED
        assert op.confirmed_at is not None

        # Start applying
        op = await store.start_applying(op.id)
        assert op.state == DecisionChangeOpState.APPLYING

        # Complete
        op = await store.complete(op.id)
        assert op.state == DecisionChangeOpState.DONE
        assert op.completed_at is not None

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_retry(self, store, decision_id):
        """Lifecycle with failure and retry: PROPOSED → ... → FAILED → APPLYING → DONE."""
        op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, "U1")
        await store.confirm(op.id)
        await store.start_applying(op.id)

        # First attempt fails
        op = await store.fail(op.id, "Network error")
        assert op.state == DecisionChangeOpState.FAILED
        assert op.error_details == "Network error"

        # Retry
        op = await store.retry(op.id)
        assert op.state == DecisionChangeOpState.APPLYING

        # Success on retry
        op = await store.complete(op.id)
        assert op.state == DecisionChangeOpState.DONE
