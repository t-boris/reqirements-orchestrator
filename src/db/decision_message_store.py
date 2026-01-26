"""Decision Message Store for canonical message operations.

Provides database operations for managing canonical Slack messages
associated with decisions. Split from decision_store.py for modularization.
"""
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.schemas.decision import (
    Alternative,
    Consequence,
    Decision,
    DecisionStatus,
    DecisionType,
    RationaleItem,
)


class DecisionMessageStore:
    """Store for Decision canonical message operations.

    Handles setting and querying the canonical Slack message
    that represents a decision in a channel.

    Usage:
        async with get_connection() as conn:
            store = DecisionMessageStore(conn)
            decision = await store.set_canonical_message(
                decision_id,
                message_ts="1234567890.123456",
            )
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def set_canonical_message(
        self,
        decision_id: str,
        message_ts: str,
        thread_ts: str | None = None,
    ) -> Decision:
        """Set the canonical Slack message for this decision.

        Args:
            decision_id: UUID of the decision.
            message_ts: Slack message timestamp of canonical message.
            thread_ts: Optional thread timestamp under canonical message.

        Returns:
            Decision: Updated decision with message tracking.

        Raises:
            ValueError: If decision not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE decisions
                SET canonical_message_ts = %s, discussion_thread_ts = %s, updated_at = %s
                WHERE id = %s
                RETURNING id, channel_id, decision_type, title, description,
                          status, version, created_by, created_at, updated_at,
                          approved_by, approved_at, replaced_by, deprecation_reason,
                          canonical_message_ts, discussion_thread_ts,
                          rationale, context_before, alternatives, consequences
                """,
                (message_ts, thread_ts, now, decision_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Decision not found: {decision_id}")

        return self._row_to_decision(row)

    async def get_by_canonical_message(
        self,
        channel_id: str,
        message_ts: str,
    ) -> Optional[Decision]:
        """Get decision by its canonical Slack message timestamp.

        Used for thread binding - when someone posts in a decision thread,
        we need to find which decision it belongs to.

        Args:
            channel_id: Slack channel ID
            message_ts: Message timestamp of the canonical message

        Returns:
            Decision if found, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, decision_type, title, description,
                       status, version, created_by, created_at, updated_at,
                       approved_by, approved_at, replaced_by, deprecation_reason,
                       canonical_message_ts, discussion_thread_ts,
                       rationale, context_before, alternatives, consequences
                FROM decisions
                WHERE channel_id = %s AND canonical_message_ts = %s
                """,
                (channel_id, message_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_decision(row)

    async def clear_canonical_message(
        self,
        decision_id: str,
    ) -> Decision:
        """Clear the canonical message for a decision.

        Args:
            decision_id: UUID of the decision.

        Returns:
            Decision: Updated decision with cleared message tracking.

        Raises:
            ValueError: If decision not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE decisions
                SET canonical_message_ts = NULL, discussion_thread_ts = NULL, updated_at = %s
                WHERE id = %s
                RETURNING id, channel_id, decision_type, title, description,
                          status, version, created_by, created_at, updated_at,
                          approved_by, approved_at, replaced_by, deprecation_reason,
                          canonical_message_ts, discussion_thread_ts,
                          rationale, context_before, alternatives, consequences
                """,
                (now, decision_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Decision not found: {decision_id}")

        return self._row_to_decision(row)

    def _row_to_decision(self, row: tuple) -> Decision:
        """Convert database row to Decision model.

        Args:
            row: Tuple from database query.
                Expected order (20 columns):
                0: id, 1: channel_id, 2: decision_type, 3: title,
                4: description, 5: status, 6: version, 7: created_by,
                8: created_at, 9: updated_at, 10: approved_by, 11: approved_at,
                12: replaced_by, 13: deprecation_reason,
                14: canonical_message_ts, 15: discussion_thread_ts,
                16: rationale (JSONB), 17: context_before (TEXT),
                18: alternatives (JSONB), 19: consequences (JSONB)

        Returns:
            Decision model instance.
        """
        # Parse JSONB fields back to models
        rationale = None
        if row[16]:
            rationale = [RationaleItem(**r) for r in row[16]]

        alternatives = None
        if row[18]:
            alternatives = [Alternative(**a) for a in row[18]]

        consequences = None
        if row[19]:
            consequences = [Consequence(**c) for c in row[19]]

        return Decision(
            id=str(row[0]),
            channel_id=row[1],
            decision_type=DecisionType(row[2]),
            title=row[3],
            description=row[4],
            status=DecisionStatus(row[5]),
            version=row[6],
            created_by=row[7],
            created_at=row[8],
            updated_at=row[9],
            approved_by=row[10],
            approved_at=row[11],
            replaced_by=str(row[12]) if row[12] else None,
            deprecation_reason=row[13],
            canonical_message_ts=row[14],
            discussion_thread_ts=row[15],
            rationale=rationale,
            context=row[17],  # context_before in DB, context in model
            alternatives=alternatives,
            consequences=consequences,
        )
