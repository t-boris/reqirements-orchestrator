"""DecisionVersionStore for version history operations.

Provides database operations for Decision version history.
Split from decision_store.py for modularization.
"""
from psycopg import AsyncConnection

from src.schemas.decision import (
    DecisionStatus,
    DecisionVersion,
)


class DecisionVersionStore:
    """Store for Decision version history operations.

    Handles retrieval of historical versions of decisions.
    Version records are created by DecisionStore.update() when decisions change.

    Usage:
        async with get_connection() as conn:
            version_store = DecisionVersionStore(conn)
            history = await version_store.get_version_history(decision_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create decision_versions table if not exists.

        Note: This is typically called by DecisionStore.create_tables()
        which creates both tables. This method is provided for standalone use.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            # Decision versions table for history
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS decision_versions (
                    id UUID PRIMARY KEY,
                    decision_id UUID NOT NULL,
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

            # Index on decision_id for version history queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_versions_decision_id
                ON decision_versions(decision_id)
            """)

            await self._conn.commit()

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
                       status, changed_by, changed_at, change_reason,
                       rationale, context_before, alternatives, consequences
                FROM decision_versions
                WHERE decision_id = %s
                ORDER BY version DESC
                """,
                (decision_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_decision_version(row) for row in rows]

    async def get_version(
        self,
        decision_id: str,
        version: int,
    ) -> DecisionVersion | None:
        """Get a specific version of a decision.

        Args:
            decision_id: UUID of the decision.
            version: Version number to retrieve.

        Returns:
            DecisionVersion if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, decision_id, version, title, description,
                       status, changed_by, changed_at, change_reason,
                       rationale, context_before, alternatives, consequences
                FROM decision_versions
                WHERE decision_id = %s AND version = %s
                """,
                (decision_id, version),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_decision_version(row)

    async def get_latest_version_number(self, decision_id: str) -> int | None:
        """Get the latest version number in history for a decision.

        Args:
            decision_id: UUID of the decision.

        Returns:
            Latest version number, or None if no history exists.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT MAX(version)
                FROM decision_versions
                WHERE decision_id = %s
                """,
                (decision_id,),
            )
            row = await cur.fetchone()

        if row and row[0] is not None:
            return row[0]
        return None

    async def count_versions(self, decision_id: str) -> int:
        """Count the number of versions for a decision.

        Args:
            decision_id: UUID of the decision.

        Returns:
            Number of version records.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*)
                FROM decision_versions
                WHERE decision_id = %s
                """,
                (decision_id,),
            )
            row = await cur.fetchone()

        return row[0] if row else 0

    def _row_to_decision_version(self, row: tuple) -> DecisionVersion:
        """Convert database row to DecisionVersion model.

        Args:
            row: Tuple from database query.
                Expected order (13 columns):
                0: id, 1: decision_id, 2: version, 3: title,
                4: description, 5: status, 6: changed_by,
                7: changed_at, 8: change_reason,
                9: rationale (JSONB), 10: context_before (TEXT),
                11: alternatives (JSONB), 12: consequences (JSONB)

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
            # Rich context (Phase 40) - stored as dict in DecisionVersion
            rationale=row[9],
            context=row[10],  # context_before in DB, context in model
            alternatives=row[11],
            consequences=row[12],
        )
