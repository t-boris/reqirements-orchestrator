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

                    -- Provenance
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    approved_by TEXT,
                    approved_at TIMESTAMPTZ,

                    -- Deprecation/replacement
                    replaced_by UUID,
                    deprecation_reason TEXT,

                    -- Slack message tracking
                    canonical_message_ts TEXT,
                    discussion_thread_ts TEXT,

                    -- Rich context fields (Phase 40)
                    rationale JSONB,
                    context_before TEXT,
                    alternatives JSONB,
                    consequences JSONB
                )
            """)

            # Migration: Add rich context columns if they don't exist (for existing tables)
            await cur.execute("""
                ALTER TABLE decisions
                ADD COLUMN IF NOT EXISTS rationale JSONB,
                ADD COLUMN IF NOT EXISTS context_before TEXT,
                ADD COLUMN IF NOT EXISTS alternatives JSONB,
                ADD COLUMN IF NOT EXISTS consequences JSONB
            """)

            # Decision versions table for history
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS decision_versions (
                    id UUID PRIMARY KEY,
                    decision_id UUID NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    changed_by TEXT NOT NULL,
                    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    change_reason TEXT,

                    -- Rich context fields (Phase 40)
                    rationale JSONB,
                    context_before TEXT,
                    alternatives JSONB,
                    consequences JSONB,

                    UNIQUE(decision_id, version)
                )
            """)

            # Migration: Add rich context columns to decision_versions if they don't exist
            await cur.execute("""
                ALTER TABLE decision_versions
                ADD COLUMN IF NOT EXISTS rationale JSONB,
                ADD COLUMN IF NOT EXISTS context_before TEXT,
                ADD COLUMN IF NOT EXISTS alternatives JSONB,
                ADD COLUMN IF NOT EXISTS consequences JSONB
            """)

            # Index on channel_id for list queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decisions_channel_id
                ON decisions(channel_id)
            """)

            # Index on status for filtering
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decisions_status
                ON decisions(status)
            """)

            # Composite index for channel + status queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decisions_channel_status
                ON decisions(channel_id, status)
            """)

            # Index on decision_id for version history queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_versions_decision_id
                ON decision_versions(decision_id)
            """)

            await self._conn.commit()

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
                       canonical_message_ts, discussion_thread_ts
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
                   canonical_message_ts, discussion_thread_ts
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
                          canonical_message_ts, discussion_thread_ts
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
                          canonical_message_ts, discussion_thread_ts
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

        Args:
            decision_id: UUID of the decision.

        Returns:
            List of DecisionVersion objects, ordered by version DESC.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, decision_id, version, title, description,
                       status, changed_by, changed_at, change_reason
                FROM decision_versions
                WHERE decision_id = %s
                ORDER BY version DESC
                """,
                (decision_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_decision_version(row) for row in rows]

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
                          canonical_message_ts, discussion_thread_ts
                """,
                (
                    message_ts,
                    thread_ts,
                    now,
                    decision_id,
                ),
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

        Used for thread binding — when someone posts in a decision thread,
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
                       canonical_message_ts, discussion_thread_ts
                FROM decisions
                WHERE channel_id = %s AND canonical_message_ts = %s
                """,
                (channel_id, message_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_decision(row)

    def _row_to_decision(self, row: tuple) -> Decision:
        """Convert database row to Decision model.

        Args:
            row: Tuple from database query.
                Expected order (16 columns):
                0: id, 1: channel_id, 2: decision_type, 3: title,
                4: description, 5: status, 6: version, 7: created_by,
                8: created_at, 9: updated_at, 10: approved_by, 11: approved_at,
                12: replaced_by, 13: deprecation_reason,
                14: canonical_message_ts, 15: discussion_thread_ts

        Returns:
            Decision model instance.
        """
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
        )

    def _row_to_decision_version(self, row: tuple) -> DecisionVersion:
        """Convert database row to DecisionVersion model.

        Args:
            row: Tuple from database query.
                Expected order (9 columns):
                0: id, 1: decision_id, 2: version, 3: title,
                4: description, 5: status, 6: changed_by,
                7: changed_at, 8: change_reason

        Returns:
            DecisionVersion model instance.
        """
        return DecisionVersion(
            id=str(row[0]),
            decision_id=str(row[1]),
            version=row[2],
            title=row[3],
            description=row[4],
            status=DecisionStatus(row[5]),
            changed_by=row[6],
            changed_at=row[7],
            change_reason=row[8],
        )
