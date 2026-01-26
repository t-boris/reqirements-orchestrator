"""DecisionStore with async CRUD operations and versioning using psycopg v3.

Provides database persistence for Decision entities with version history.
Decisions are versioned - every update creates a new version.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from psycopg import AsyncConnection
from psycopg.types.json import Json

from src.schemas.decision import (
    Alternative,
    Consequence,
    Decision,
    DecisionChangeOp,
    DecisionChangeOpType,
    DecisionStatus,
    DecisionType,
    DecisionVersion,
    RationaleItem,
)


class DecisionStore:
    """Store for Decision entities with versioning.

    Decisions are versioned - every update creates a new version.
    Old versions are preserved in decision_versions table.

    Usage:
        async with get_connection() as conn:
            store = DecisionStore(conn)
            decision = await store.create(
                channel_id,
                DecisionType.ARCH,
                "Use PostgreSQL",
                "We will use PostgreSQL for...",
                user_id,
            )
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create decisions and decision_versions tables if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        from src.db.decision_version_store import DecisionVersionStore

        async with self._conn.cursor() as cur:
            # Main decisions table
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    approved_by TEXT,
                    approved_at TIMESTAMPTZ,
                    replaced_by UUID,
                    deprecation_reason TEXT,
                    canonical_message_ts TEXT,
                    discussion_thread_ts TEXT,
                    rationale JSONB,
                    context_before TEXT,
                    alternatives JSONB,
                    consequences JSONB
                )
            """)

            # Migration: Add rich context columns if they don't exist
            await cur.execute("""
                ALTER TABLE decisions
                ADD COLUMN IF NOT EXISTS rationale JSONB,
                ADD COLUMN IF NOT EXISTS context_before TEXT,
                ADD COLUMN IF NOT EXISTS alternatives JSONB,
                ADD COLUMN IF NOT EXISTS consequences JSONB
            """)

            # Indexes for decisions table
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decisions_channel_id ON decisions(channel_id)
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status)
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decisions_channel_status ON decisions(channel_id, status)
            """)

            await self._conn.commit()

        # Delegate version table creation to DecisionVersionStore
        version_store = DecisionVersionStore(self._conn)
        await version_store.create_tables()

    async def create(
        self,
        channel_id: str,
        decision_type: DecisionType,
        title: str,
        description: str,
        created_by: str,
        *,
        discussion_thread_ts: Optional[str] = None,
        # Rich context (Phase 40)
        rationale: Optional[list[dict]] = None,
        context_before: Optional[str] = None,
        alternatives: Optional[list[dict]] = None,
        consequences: Optional[list[dict]] = None,
    ) -> Decision:
        """Create a new decision in PROPOSED status.

        Args:
            channel_id: Slack channel ID.
            decision_type: Type of decision (ARCH, SCOPE, etc.).
            title: Short description of the decision.
            description: Full explanation of the decision.
            created_by: User ID who created the decision.
            discussion_thread_ts: Optional thread timestamp for discussion.
            rationale: Optional list of rationale items (Phase 40).
            context_before: Optional status quo context (Phase 40).
            alternatives: Optional list of considered alternatives (Phase 40).
            consequences: Optional list of consequences (Phase 40).

        Returns:
            Decision: Newly created decision with version=1 and PROPOSED status.
        """
        decision_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO decisions (
                    id, channel_id, decision_type, title, description,
                    status, version, created_by, created_at, updated_at,
                    discussion_thread_ts,
                    rationale, context_before, alternatives, consequences
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, channel_id, decision_type, title, description,
                          status, version, created_by, created_at, updated_at,
                          approved_by, approved_at, replaced_by, deprecation_reason,
                          canonical_message_ts, discussion_thread_ts,
                          rationale, context_before, alternatives, consequences
                """,
                (
                    decision_id,
                    channel_id,
                    decision_type.value,
                    title,
                    description,
                    DecisionStatus.PROPOSED.value,
                    1,
                    created_by,
                    now,
                    now,
                    discussion_thread_ts,
                    Json(rationale) if rationale else None,
                    context_before,
                    Json(alternatives) if alternatives else None,
                    Json(consequences) if consequences else None,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_decision(row)

    async def get(self, decision_id: str) -> Optional[Decision]:
        """Get decision by ID.

        Args:
            decision_id: UUID of the decision.

        Returns:
            Decision if found, None otherwise.
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
                WHERE id = %s
                """,
                (decision_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_decision(row)

    async def list_by_channel(
        self,
        channel_id: str,
        *,
        status: list[DecisionStatus] | None = None,
        decision_type: DecisionType | None = None,
        limit: int = 50,
    ) -> list[Decision]:
        """List decisions for a channel with filters.

        Args:
            channel_id: Slack channel ID.
            status: Optional list of statuses to filter by.
            decision_type: Optional type filter.
            limit: Maximum decisions to return.

        Returns:
            List of Decision objects, ordered by updated_at DESC.
        """
        query = """
            SELECT id, channel_id, decision_type, title, description,
                   status, version, created_by, created_at, updated_at,
                   approved_by, approved_at, replaced_by, deprecation_reason,
                   canonical_message_ts, discussion_thread_ts,
                   rationale, context_before, alternatives, consequences
            FROM decisions
            WHERE channel_id = %s
        """
        params: list[Any] = [channel_id]

        if status is not None:
            status_values = [s.value for s in status]
            placeholders = ", ".join(["%s"] * len(status_values))
            query += f" AND status IN ({placeholders})"
            params.extend(status_values)

        if decision_type is not None:
            query += " AND decision_type = %s"
            params.append(decision_type.value)

        query += " ORDER BY updated_at DESC LIMIT %s"
        params.append(limit)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_decision(row) for row in rows]

    async def update(
        self,
        decision_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        changed_by: str,
        change_reason: str | None = None,
        # Rich context (Phase 40)
        rationale: list[dict] | None = None,
        context_before: str | None = None,
        alternatives: list[dict] | None = None,
        consequences: list[dict] | None = None,
    ) -> Decision:
        """Update decision, creating new version.

        Before updating, saves current state to decision_versions table.
        Increments version number.

        Args:
            decision_id: UUID of the decision to update.
            title: New title if provided.
            description: New description if provided.
            changed_by: User ID who made this change.
            change_reason: Optional reason for the change.
            rationale: New rationale if provided (Phase 40).
            context_before: New context if provided (Phase 40).
            alternatives: New alternatives if provided (Phase 40).
            consequences: New consequences if provided (Phase 40).

        Returns:
            Decision: Updated decision with incremented version.

        Raises:
            ValueError: If decision not found.
        """
        # Get current decision to save version history
        current = await self.get(decision_id)
        if not current:
            raise ValueError(f"Decision not found: {decision_id}")

        # Save current version to history (including rich context)
        version_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Serialize current rich context for version history
        current_rationale = None
        if current.rationale:
            current_rationale = [r.model_dump() for r in current.rationale]
        current_alternatives = None
        if current.alternatives:
            current_alternatives = [a.model_dump() for a in current.alternatives]
        current_consequences = None
        if current.consequences:
            current_consequences = [c.model_dump() for c in current.consequences]

        async with self._conn.cursor() as cur:
            # Insert version history record with rich context
            await cur.execute(
                """
                INSERT INTO decision_versions (
                    id, decision_id, version, title, description,
                    status, changed_by, changed_at, change_reason,
                    rationale, context_before, alternatives, consequences
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version_id,
                    decision_id,
                    current.version,
                    current.title,
                    current.description,
                    current.status.value,
                    changed_by,
                    now,
                    change_reason,
                    Json(current_rationale) if current_rationale else None,
                    current.context,
                    Json(current_alternatives) if current_alternatives else None,
                    Json(current_consequences) if current_consequences else None,
                ),
            )

            # Build update query
            set_clauses: list[str] = []
            params: list[Any] = []

            if title is not None:
                set_clauses.append("title = %s")
                params.append(title)

            if description is not None:
                set_clauses.append("description = %s")
                params.append(description)

            # Rich context fields (Phase 40)
            if rationale is not None:
                set_clauses.append("rationale = %s")
                params.append(Json(rationale))

            if context_before is not None:
                set_clauses.append("context_before = %s")
                params.append(context_before)

            if alternatives is not None:
                set_clauses.append("alternatives = %s")
                params.append(Json(alternatives))

            if consequences is not None:
                set_clauses.append("consequences = %s")
                params.append(Json(consequences))

            # Always increment version and update timestamp
            set_clauses.append("version = version + 1")
            set_clauses.append("updated_at = %s")
            params.append(now)

            params.append(decision_id)

            query = f"""
                UPDATE decisions
                SET {', '.join(set_clauses)}
                WHERE id = %s
                RETURNING id, channel_id, decision_type, title, description,
                          status, version, created_by, created_at, updated_at,
                          approved_by, approved_at, replaced_by, deprecation_reason,
                          canonical_message_ts, discussion_thread_ts,
                          rationale, context_before, alternatives, consequences
            """

            await cur.execute(query, params)
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Decision not found: {decision_id}")

        return self._row_to_decision(row)

    async def approve(
        self,
        decision_id: str,
        approved_by: str,
    ) -> Decision:
        """Approve a decision (PROPOSED -> APPROVED).

        Args:
            decision_id: UUID of the decision to approve.
            approved_by: User ID who approved.

        Returns:
            Decision: Updated decision with APPROVED status.

        Raises:
            ValueError: If decision not found or not in PROPOSED status.
        """
        current = await self.get(decision_id)
        if not current:
            raise ValueError(f"Decision not found: {decision_id}")

        if current.status != DecisionStatus.PROPOSED:
            raise ValueError(
                f"Decision {decision_id} is {current.status.value}, not proposed"
            )

        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE decisions
                SET status = %s, approved_by = %s, approved_at = %s, updated_at = %s
                WHERE id = %s
                RETURNING id, channel_id, decision_type, title, description,
                          status, version, created_by, created_at, updated_at,
                          approved_by, approved_at, replaced_by, deprecation_reason,
                          canonical_message_ts, discussion_thread_ts,
                          rationale, context_before, alternatives, consequences
                """,
                (
                    DecisionStatus.APPROVED.value,
                    approved_by,
                    now,
                    now,
                    decision_id,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Decision not found: {decision_id}")

        return self._row_to_decision(row)

    async def deprecate(
        self,
        decision_id: str,
        deprecated_by: str,
        reason: str,
        replaced_by: str | None = None,
    ) -> Decision:
        """Deprecate a decision.

        Args:
            decision_id: UUID of the decision to deprecate.
            deprecated_by: User ID who deprecated.
            reason: Why this decision was deprecated.
            replaced_by: Optional ID of replacement decision.

        Returns:
            Decision: Updated decision with DEPRECATED or REPLACED status.

        Raises:
            ValueError: If decision not found.
        """
        current = await self.get(decision_id)
        if not current:
            raise ValueError(f"Decision not found: {decision_id}")

        status = DecisionStatus.REPLACED if replaced_by else DecisionStatus.DEPRECATED
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE decisions
                SET status = %s, deprecation_reason = %s, replaced_by = %s, updated_at = %s
                WHERE id = %s
                RETURNING id, channel_id, decision_type, title, description,
                          status, version, created_by, created_at, updated_at,
                          approved_by, approved_at, replaced_by, deprecation_reason,
                          canonical_message_ts, discussion_thread_ts,
                          rationale, context_before, alternatives, consequences
                """,
                (
                    status.value,
                    reason,
                    replaced_by,
                    now,
                    decision_id,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Decision not found: {decision_id}")

        return self._row_to_decision(row)

    async def get_version_history(
        self,
        decision_id: str,
    ) -> list[DecisionVersion]:
        """Get all historical versions of a decision.

        Delegates to DecisionVersionStore for the actual query.

        Args:
            decision_id: UUID of the decision.

        Returns:
            List of DecisionVersion objects, ordered by version DESC.
        """
        from src.db.decision_version_store import DecisionVersionStore

        version_store = DecisionVersionStore(self._conn)
        return await version_store.get_version_history(decision_id)

    async def set_canonical_message(
        self,
        decision_id: str,
        message_ts: str,
        thread_ts: str | None = None,
    ) -> Decision:
        """Set the canonical Slack message for this decision.

        Delegates to DecisionMessageStore.
        """
        from src.db.decision_message_store import DecisionMessageStore

        store = DecisionMessageStore(self._conn)
        return await store.set_canonical_message(decision_id, message_ts, thread_ts)

    async def get_by_canonical_message(
        self,
        channel_id: str,
        message_ts: str,
    ) -> Optional[Decision]:
        """Get decision by its canonical Slack message timestamp.

        Delegates to DecisionMessageStore.
        """
        from src.db.decision_message_store import DecisionMessageStore

        store = DecisionMessageStore(self._conn)
        return await store.get_by_canonical_message(channel_id, message_ts)

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

        Delegates to DecisionRichContextStore.

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
        from src.db.decision_rich_context_store import DecisionRichContextStore

        store = DecisionRichContextStore(self._conn)
        return await store.update_rich_context(
            decision_id,
            rationale=rationale,
            context_before=context_before,
            alternatives=alternatives,
            consequences=consequences,
            updated_by=updated_by,
        )

    async def list_without_rich_context(
        self,
        channel_id: str,
        *,
        limit: int = 20,
    ) -> list[Decision]:
        """List decisions in channel that lack rich context.

        Delegates to DecisionRichContextStore.

        Args:
            channel_id: Slack channel ID
            limit: Maximum decisions to return

        Returns:
            List of Decision objects without rich context
        """
        from src.db.decision_rich_context_store import DecisionRichContextStore

        store = DecisionRichContextStore(self._conn)
        return await store.list_without_rich_context(channel_id, limit=limit)

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
        # Parse JSONB fields back to models (Phase 40)
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
            # Rich context (Phase 40)
            rationale=rationale,
            context=row[17],  # context_before in DB, context in model
            alternatives=alternatives,
            consequences=consequences,
        )


    # =========================================================================
    # Change Operation Helpers (Phase 41)
    # =========================================================================

    async def create_change_op(
        self,
        decision_id: str,
        operation: DecisionChangeOpType,
        actor: str,
    ) -> tuple[Decision, DecisionChangeOp]:
        """Create a change operation for a decision.

        Helper method that creates a DecisionChangeOp tracking entry
        for the specified operation. Use this when you need to track
        decision changes through the PROPOSED → CONFIRMED → APPLYING → DONE
        lifecycle.

        Args:
            decision_id: UUID of the decision to change
            operation: Type of change (EDIT, DEPRECATE, DELETE)
            actor: User ID who initiated the change

        Returns:
            Tuple of (Decision, DecisionChangeOp) - the current decision
            and the newly created change op in PROPOSED state

        Raises:
            ValueError: If decision not found
        """
        # Import here to avoid circular import
        from src.db.decision_change_op_store import DecisionChangeOpStore

        decision = await self.get(decision_id)
        if not decision:
            raise ValueError(f"Decision not found: {decision_id}")

        # Create the change op store using same connection
        op_store = DecisionChangeOpStore(self._conn)
        await op_store.create_tables()  # Ensure table exists

        # Determine to_version based on operation
        to_version: int | None = None
        if operation == DecisionChangeOpType.EDIT:
            to_version = decision.version + 1

        change_op = await op_store.create(
            decision_id=decision_id,
            operation=operation,
            from_version=decision.version,
            to_version=to_version,
            actor=actor,
        )

        return decision, change_op
