"""DecisionChangeOpStore for tracking decision change operations.

Every decision change (edit, deprecate, delete) goes through a lifecycle:
PROPOSED → CONFIRMED → APPLYING → DONE/FAILED/CANCELLED

This enables:
- Impact analysis before applying
- User confirmation with full visibility
- Transactional application (DB → Slack → Jira)
- Rollback on failure
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection
from psycopg.types.json import Json

from src.schemas.decision import (
    DecisionChangeOp,
    DecisionChangeOpState,
    DecisionChangeOpType,
    ImpactSummary,
)

logger = logging.getLogger(__name__)


# =============================================================================
# State Machine Validation
# =============================================================================

VALID_TRANSITIONS: dict[DecisionChangeOpState, set[DecisionChangeOpState]] = {
    DecisionChangeOpState.PROPOSED: {
        DecisionChangeOpState.CONFIRMED,
        DecisionChangeOpState.CANCELLED,
    },
    DecisionChangeOpState.CONFIRMED: {
        DecisionChangeOpState.APPLYING,
        DecisionChangeOpState.CANCELLED,
    },
    DecisionChangeOpState.APPLYING: {
        DecisionChangeOpState.DONE,
        DecisionChangeOpState.FAILED,
    },
    DecisionChangeOpState.FAILED: {
        DecisionChangeOpState.APPLYING,  # retry
        DecisionChangeOpState.CANCELLED,
    },
    DecisionChangeOpState.DONE: set(),  # terminal
    DecisionChangeOpState.CANCELLED: set(),  # terminal
}


def validate_transition(
    current: DecisionChangeOpState,
    target: DecisionChangeOpState,
) -> None:
    """Validate state transition is allowed.

    Args:
        current: Current state of the operation
        target: Target state to transition to

    Raises:
        ValueError: If transition is not allowed
    """
    if target not in VALID_TRANSITIONS[current]:
        valid = ", ".join(s.value for s in VALID_TRANSITIONS[current]) or "(none)"
        raise ValueError(
            f"Invalid state transition: {current.value} → {target.value}. "
            f"Valid transitions from {current.value}: {valid}"
        )


class DecisionChangeOpStore:
    """Store for DecisionChangeOp entities.

    Tracks decision change operations through their lifecycle.

    Usage:
        async with get_connection() as conn:
            store = DecisionChangeOpStore(conn)
            op = await store.create(decision_id, DecisionChangeOpType.EDIT, 1, 2, user_id)
            await store.confirm(op.id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create decision_change_ops table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS decision_change_ops (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    decision_id UUID NOT NULL,
                    operation TEXT NOT NULL,
                    from_version INTEGER NOT NULL,
                    to_version INTEGER,
                    actor TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'proposed',
                    impact_summary JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    confirmed_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    error_details TEXT
                )
            """)

            # Index on decision_id for filtering ops by decision
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_change_ops_decision
                ON decision_change_ops(decision_id)
            """)

            # Index on state for finding pending/in-progress ops
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_change_ops_state
                ON decision_change_ops(state)
            """)

            await self._conn.commit()

    def _row_to_op(self, row: tuple) -> DecisionChangeOp:
        """Convert database row to DecisionChangeOp.

        Args:
            row: Tuple from database query with columns:
                 id, decision_id, operation, from_version, to_version,
                 actor, state, impact_summary, created_at, confirmed_at,
                 completed_at, error_details

        Returns:
            DecisionChangeOp instance.
        """
        impact_summary = None
        if row[7]:
            impact_summary = ImpactSummary(**row[7])

        return DecisionChangeOp(
            id=str(row[0]),
            decision_id=str(row[1]),
            operation=DecisionChangeOpType(row[2]),
            from_version=row[3],
            to_version=row[4],
            actor=row[5],
            state=DecisionChangeOpState(row[6]),
            impact_summary=impact_summary,
            created_at=row[8],
            confirmed_at=row[9],
            completed_at=row[10],
            error_details=row[11],
        )

    async def create(
        self,
        decision_id: str,
        operation: DecisionChangeOpType,
        from_version: int,
        to_version: int | None,
        actor: str,
    ) -> DecisionChangeOp:
        """Create a new change operation in PROPOSED state.

        Args:
            decision_id: UUID of the target decision
            operation: Type of change (EDIT, DEPRECATE, DELETE)
            from_version: Current version of the decision
            to_version: Target version (None for deprecate/delete)
            actor: User ID who initiated the change

        Returns:
            DecisionChangeOp in PROPOSED state
        """
        op_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO decision_change_ops (
                    id, decision_id, operation, from_version, to_version,
                    actor, state, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, decision_id, operation, from_version, to_version,
                          actor, state, impact_summary, created_at, confirmed_at,
                          completed_at, error_details
                """,
                (
                    op_id,
                    decision_id,
                    operation.value,
                    from_version,
                    to_version,
                    actor,
                    DecisionChangeOpState.PROPOSED.value,
                    now,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        logger.info(
            "Decision change operation created",
            extra={
                "op_id": op_id,
                "decision_id": decision_id,
                "operation": operation.value,
                "from_version": from_version,
                "to_version": to_version,
                "actor": actor,
            },
        )

        return self._row_to_op(row)

    async def get(self, op_id: str) -> Optional[DecisionChangeOp]:
        """Get change operation by ID.

        Args:
            op_id: UUID of the operation

        Returns:
            DecisionChangeOp if found, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, decision_id, operation, from_version, to_version,
                       actor, state, impact_summary, created_at, confirmed_at,
                       completed_at, error_details
                FROM decision_change_ops
                WHERE id = %s
                """,
                (op_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_op(row)

    async def get_for_decision(
        self,
        decision_id: str,
        *,
        state: DecisionChangeOpState | None = None,
    ) -> list[DecisionChangeOp]:
        """Get all change operations for a decision.

        Args:
            decision_id: UUID of the decision
            state: Optional state filter

        Returns:
            List of DecisionChangeOp ordered by created_at DESC
        """
        query = """
            SELECT id, decision_id, operation, from_version, to_version,
                   actor, state, impact_summary, created_at, confirmed_at,
                   completed_at, error_details
            FROM decision_change_ops
            WHERE decision_id = %s
        """
        params: list = [decision_id]

        if state is not None:
            query += " AND state = %s"
            params.append(state.value)

        query += " ORDER BY created_at DESC"

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_op(row) for row in rows]

    async def update_state(
        self,
        op_id: str,
        state: DecisionChangeOpState,
        *,
        error_details: str | None = None,
    ) -> DecisionChangeOp:
        """Transition operation to a new state.

        Validates the transition is allowed before applying.

        Args:
            op_id: UUID of the operation
            state: Target state
            error_details: Optional error message (for FAILED state)

        Returns:
            Updated DecisionChangeOp

        Raises:
            ValueError: If operation not found or transition invalid
        """
        current = await self.get(op_id)
        if not current:
            raise ValueError(f"Operation not found: {op_id}")

        validate_transition(current.state, state)

        now = datetime.now(timezone.utc)

        # Set completed_at for terminal states
        completed_at = None
        if state in (
            DecisionChangeOpState.DONE,
            DecisionChangeOpState.FAILED,
            DecisionChangeOpState.CANCELLED,
        ):
            completed_at = now

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE decision_change_ops
                SET state = %s, completed_at = %s, error_details = %s
                WHERE id = %s
                RETURNING id, decision_id, operation, from_version, to_version,
                          actor, state, impact_summary, created_at, confirmed_at,
                          completed_at, error_details
                """,
                (state.value, completed_at, error_details, op_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        logger.info(
            "Decision change operation state updated",
            extra={
                "op_id": op_id,
                "from_state": current.state.value,
                "to_state": state.value,
            },
        )

        return self._row_to_op(row)

    async def set_impact(
        self,
        op_id: str,
        impact_summary: ImpactSummary,
    ) -> DecisionChangeOp:
        """Set impact analysis result on operation.

        Args:
            op_id: UUID of the operation
            impact_summary: Results of impact analysis

        Returns:
            Updated DecisionChangeOp

        Raises:
            ValueError: If operation not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE decision_change_ops
                SET impact_summary = %s
                WHERE id = %s
                RETURNING id, decision_id, operation, from_version, to_version,
                          actor, state, impact_summary, created_at, confirmed_at,
                          completed_at, error_details
                """,
                (Json(impact_summary.model_dump()), op_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Operation not found: {op_id}")

        logger.info(
            "Impact summary set on operation",
            extra={
                "op_id": op_id,
                "jira_keys": impact_summary.jira_keys,
                "total_affected": impact_summary.total_affected,
                "conflict_count": impact_summary.conflict_count,
            },
        )

        return self._row_to_op(row)

    async def confirm(self, op_id: str) -> DecisionChangeOp:
        """Confirm operation (PROPOSED → CONFIRMED).

        Args:
            op_id: UUID of the operation

        Returns:
            Updated DecisionChangeOp in CONFIRMED state

        Raises:
            ValueError: If operation not found or not in PROPOSED state
        """
        current = await self.get(op_id)
        if not current:
            raise ValueError(f"Operation not found: {op_id}")

        validate_transition(current.state, DecisionChangeOpState.CONFIRMED)

        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE decision_change_ops
                SET state = %s, confirmed_at = %s
                WHERE id = %s
                RETURNING id, decision_id, operation, from_version, to_version,
                          actor, state, impact_summary, created_at, confirmed_at,
                          completed_at, error_details
                """,
                (DecisionChangeOpState.CONFIRMED.value, now, op_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        logger.info(
            "Decision change operation confirmed",
            extra={"op_id": op_id, "decision_id": current.decision_id},
        )

        return self._row_to_op(row)

    async def cancel(self, op_id: str) -> DecisionChangeOp:
        """Cancel operation (from PROPOSED, CONFIRMED, or FAILED).

        Args:
            op_id: UUID of the operation

        Returns:
            Updated DecisionChangeOp in CANCELLED state

        Raises:
            ValueError: If operation not found or cannot be cancelled
        """
        return await self.update_state(op_id, DecisionChangeOpState.CANCELLED)

    async def complete(self, op_id: str) -> DecisionChangeOp:
        """Mark operation as complete (APPLYING → DONE).

        Args:
            op_id: UUID of the operation

        Returns:
            Updated DecisionChangeOp in DONE state

        Raises:
            ValueError: If operation not found or not in APPLYING state
        """
        return await self.update_state(op_id, DecisionChangeOpState.DONE)

    async def fail(self, op_id: str, error_details: str) -> DecisionChangeOp:
        """Mark operation as failed (APPLYING → FAILED).

        Args:
            op_id: UUID of the operation
            error_details: Error message explaining the failure

        Returns:
            Updated DecisionChangeOp in FAILED state

        Raises:
            ValueError: If operation not found or not in APPLYING state
        """
        return await self.update_state(
            op_id, DecisionChangeOpState.FAILED, error_details=error_details
        )

    async def start_applying(self, op_id: str) -> DecisionChangeOp:
        """Start applying operation (CONFIRMED → APPLYING).

        Args:
            op_id: UUID of the operation

        Returns:
            Updated DecisionChangeOp in APPLYING state

        Raises:
            ValueError: If operation not found or not in CONFIRMED state
        """
        return await self.update_state(op_id, DecisionChangeOpState.APPLYING)

    async def retry(self, op_id: str) -> DecisionChangeOp:
        """Retry failed operation (FAILED → APPLYING).

        Args:
            op_id: UUID of the operation

        Returns:
            Updated DecisionChangeOp in APPLYING state

        Raises:
            ValueError: If operation not found or not in FAILED state
        """
        return await self.update_state(op_id, DecisionChangeOpState.APPLYING)

    async def get_pending_for_decision(
        self,
        decision_id: str,
    ) -> Optional[DecisionChangeOp]:
        """Get the most recent pending (non-terminal) operation for a decision.

        Used to check if a decision has an in-flight change operation.

        Args:
            decision_id: UUID of the decision

        Returns:
            Most recent non-terminal DecisionChangeOp, or None
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, decision_id, operation, from_version, to_version,
                       actor, state, impact_summary, created_at, confirmed_at,
                       completed_at, error_details
                FROM decision_change_ops
                WHERE decision_id = %s
                  AND state NOT IN ('done', 'cancelled')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (decision_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_op(row)
