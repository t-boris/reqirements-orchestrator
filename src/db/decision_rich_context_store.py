"""Decision Rich Context Store for context enrichment operations.

Provides database operations for managing rich context on decisions.
Split from decision_store.py for modularization.

Rich context includes:
- Rationale: Why this decision was made
- Context before: What was the status quo
- Alternatives: What other options were considered
- Consequences: What are the implications
"""
from datetime import datetime, timezone

from psycopg import AsyncConnection
from psycopg.types.json import Json

from src.schemas.decision import (
    Alternative,
    Consequence,
    Decision,
    DecisionStatus,
    DecisionType,
    RationaleItem,
)


class DecisionRichContextStore:
    """Store for Decision rich context operations.

    Handles enrichment of decisions with context information
    without creating version history entries.

    Usage:
        async with get_connection() as conn:
            store = DecisionRichContextStore(conn)
            decision = await store.update_rich_context(
                decision_id,
                rationale=[...],
                updated_by="user123",
            )
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def update_rich_context(
        self,
        decision_id: str,
        *,
        rationale: list[dict] | None = None,
        context_before: str | None = None,
        alternatives: list[dict] | None = None,
        consequences: list[dict] | None = None,
        updated_by: str,
    ) -> Decision:
        """Update only rich context fields (backfill operation).

        Unlike DecisionStore.update(), this does NOT create a version
        history entry or increment the version number. Used for enriching
        existing decisions with extracted context.

        Args:
            decision_id: UUID of the decision
            rationale: Rationale items to set
            context_before: Context before decision
            alternatives: Alternatives considered
            consequences: Consequences of decision
            updated_by: User ID performing the update

        Returns:
            Updated Decision

        Raises:
            ValueError: If decision not found
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE decisions
                SET rationale = %s,
                    context_before = %s,
                    alternatives = %s,
                    consequences = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING id, channel_id, decision_type, title, description,
                          status, version, created_by, created_at, updated_at,
                          approved_by, approved_at, replaced_by, deprecation_reason,
                          canonical_message_ts, discussion_thread_ts,
                          rationale, context_before, alternatives, consequences
                """,
                (
                    Json(rationale) if rationale else None,
                    context_before,
                    Json(alternatives) if alternatives else None,
                    Json(consequences) if consequences else None,
                    now,
                    decision_id,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Decision not found: {decision_id}")

        return self._row_to_decision(row)

    async def list_without_rich_context(
        self,
        channel_id: str,
        *,
        limit: int = 20,
    ) -> list[Decision]:
        """List decisions in channel that lack rich context.

        Useful for identifying decisions that need enrichment.

        Args:
            channel_id: Slack channel ID
            limit: Maximum decisions to return

        Returns:
            List of Decision objects without rich context
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
                WHERE channel_id = %s
                  AND rationale IS NULL
                  AND context_before IS NULL
                  AND alternatives IS NULL
                  AND consequences IS NULL
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (channel_id, limit),
            )
            rows = await cur.fetchall()

        return [self._row_to_decision(row) for row in rows]

    async def has_rich_context(self, decision_id: str) -> bool:
        """Check if a decision has any rich context set.

        Args:
            decision_id: UUID of the decision

        Returns:
            True if any rich context field is non-null
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    rationale IS NOT NULL OR
                    context_before IS NOT NULL OR
                    alternatives IS NOT NULL OR
                    consequences IS NOT NULL
                FROM decisions
                WHERE id = %s
                """,
                (decision_id,),
            )
            row = await cur.fetchone()

        return bool(row and row[0])

    async def clear_rich_context(
        self,
        decision_id: str,
        updated_by: str,
    ) -> Decision:
        """Clear all rich context fields.

        Args:
            decision_id: UUID of the decision
            updated_by: User ID performing the update

        Returns:
            Updated Decision with cleared context

        Raises:
            ValueError: If decision not found
        """
        return await self.update_rich_context(
            decision_id,
            rationale=None,
            context_before=None,
            alternatives=None,
            consequences=None,
            updated_by=updated_by,
        )

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
