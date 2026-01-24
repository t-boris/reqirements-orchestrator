"""Decision Link Store for mapping decisions to Jira fields.

Tracks which decisions are linked to which Jira tickets
and at which version they were last synced.

This enables the "Jira as projection" model:
- Decision is the source of truth
- DecisionLink tracks what needs to sync to Jira
- Sync tracking enables incremental updates
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.schemas.decision import DecisionLink, JiraFieldPath

logger = logging.getLogger(__name__)


class DecisionLinkStore:
    """Store for Decision -> Jira mappings.

    Tracks which decisions are linked to which Jira tickets
    and at which version they were last synced.

    Usage:
        async with get_connection() as conn:
            store = DecisionLinkStore(conn)
            await store.link(decision_id, "SCRUM-123", JiraFieldPath.DESC_ARCHITECTURE, user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create decision_links table if not exists.

        Columns:
        - id UUID PRIMARY KEY
        - decision_id UUID NOT NULL
        - jira_key TEXT NOT NULL
        - field_path TEXT NOT NULL
        - linked_at TIMESTAMPTZ NOT NULL
        - linked_by TEXT NOT NULL
        - synced_version INT
        - synced_at TIMESTAMPTZ

        Indexes:
        - decision_id (for getting all links for a decision)
        - jira_key (for getting all decisions affecting a ticket)
        - UNIQUE(decision_id, jira_key, field_path)

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS decision_links (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    decision_id UUID NOT NULL,
                    jira_key TEXT NOT NULL,
                    field_path TEXT NOT NULL,
                    linked_at TIMESTAMPTZ NOT NULL,
                    linked_by TEXT NOT NULL,
                    synced_version INT,
                    synced_at TIMESTAMPTZ,
                    UNIQUE(decision_id, jira_key, field_path)
                )
            """)

            # Index for efficient decision lookups
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_links_decision
                ON decision_links (decision_id)
            """)

            # Index for efficient ticket lookups
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_decision_links_jira_key
                ON decision_links (jira_key)
            """)

            await self._conn.commit()

    def _row_to_link(self, row: tuple) -> DecisionLink:
        """Convert database row to DecisionLink.

        Args:
            row: Tuple from database query with columns:
                 id, decision_id, jira_key, field_path, linked_at, linked_by,
                 synced_version, synced_at

        Returns:
            DecisionLink instance.
        """
        return DecisionLink(
            id=str(row[0]),
            decision_id=str(row[1]),
            jira_key=row[2],
            field_path=JiraFieldPath(row[3]),
            linked_at=row[4],
            linked_by=row[5],
            synced_version=row[6] if len(row) > 6 else None,
            synced_at=row[7] if len(row) > 7 else None,
        )

    async def link(
        self,
        decision_id: str,
        jira_key: str,
        field_path: JiraFieldPath,
        linked_by: str,
    ) -> DecisionLink:
        """Link a decision to a Jira ticket field.

        Uses UPSERT - if already linked, updates linked_at/by.

        Args:
            decision_id: UUID of the decision.
            jira_key: Jira issue key (e.g., "SCRUM-123").
            field_path: Where in Jira the decision should appear.
            linked_by: User ID who created the link.

        Returns:
            DecisionLink: The created or updated link record.
        """
        now = datetime.now(timezone.utc)
        # Normalize jira_key to uppercase
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO decision_links (
                    decision_id, jira_key, field_path, linked_at, linked_by
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (decision_id, jira_key, field_path) DO UPDATE SET
                    linked_at = EXCLUDED.linked_at,
                    linked_by = EXCLUDED.linked_by
                RETURNING id, decision_id, jira_key, field_path, linked_at, linked_by, synced_version, synced_at
                """,
                (decision_id, jira_key, field_path.value, now, linked_by),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        logger.info(
            "Decision linked to Jira ticket",
            extra={
                "decision_id": decision_id,
                "jira_key": jira_key,
                "field_path": field_path.value,
                "linked_by": linked_by,
            },
        )

        return self._row_to_link(row)

    async def unlink(
        self,
        decision_id: str,
        jira_key: str,
    ) -> bool:
        """Remove link between decision and Jira ticket.

        Removes all links for the decision-ticket pair (regardless of field_path).

        Args:
            decision_id: UUID of the decision.
            jira_key: Jira issue key.

        Returns:
            True if any links were removed, False if not found.
        """
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM decision_links
                WHERE decision_id = %s AND jira_key = %s
                RETURNING jira_key
                """,
                (decision_id, jira_key),
            )
            rows = await cur.fetchall()
            await self._conn.commit()

        if rows:
            logger.info(
                "Decision unlinked from Jira ticket",
                extra={
                    "decision_id": decision_id,
                    "jira_key": jira_key,
                    "links_removed": len(rows),
                },
            )
            return True

        return False

    async def get_links_for_decision(
        self,
        decision_id: str,
    ) -> list[DecisionLink]:
        """Get all Jira tickets linked to a decision.

        Args:
            decision_id: UUID of the decision.

        Returns:
            List of DecisionLink ordered by linked_at descending.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, decision_id, jira_key, field_path, linked_at, linked_by, synced_version, synced_at
                FROM decision_links
                WHERE decision_id = %s
                ORDER BY linked_at DESC
                """,
                (decision_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_link(row) for row in rows]

    async def get_decisions_for_ticket(
        self,
        jira_key: str,
    ) -> list[DecisionLink]:
        """Get all decisions affecting a Jira ticket.

        Args:
            jira_key: Jira issue key.

        Returns:
            List of DecisionLink ordered by linked_at descending.
        """
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, decision_id, jira_key, field_path, linked_at, linked_by, synced_version, synced_at
                FROM decision_links
                WHERE jira_key = %s
                ORDER BY linked_at DESC
                """,
                (jira_key,),
            )
            rows = await cur.fetchall()

        return [self._row_to_link(row) for row in rows]

    async def mark_synced(
        self,
        decision_id: str,
        jira_key: str,
        version: int,
    ) -> DecisionLink | None:
        """Mark a link as synced at a specific decision version.

        Called after successfully syncing a decision to Jira.

        Args:
            decision_id: UUID of the decision.
            jira_key: Jira issue key.
            version: Decision version that was synced.

        Returns:
            Updated DecisionLink if found, None otherwise.
        """
        jira_key = jira_key.upper()
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE decision_links
                SET synced_version = %s, synced_at = %s
                WHERE decision_id = %s AND jira_key = %s
                RETURNING id, decision_id, jira_key, field_path, linked_at, linked_by, synced_version, synced_at
                """,
                (version, now, decision_id, jira_key),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            logger.debug(
                "Link not found for mark_synced",
                extra={
                    "decision_id": decision_id,
                    "jira_key": jira_key,
                },
            )
            return None

        logger.info(
            "Decision sync marked complete",
            extra={
                "decision_id": decision_id,
                "jira_key": jira_key,
                "synced_version": version,
            },
        )
        return self._row_to_link(row)

    async def get_pending_syncs(
        self,
        decision_id: str,
        current_version: int,
    ) -> list[DecisionLink]:
        """Get links that need syncing (synced_version < current_version).

        Used to find tickets that need to be updated when a decision changes.

        Args:
            decision_id: UUID of the decision.
            current_version: Current version of the decision.

        Returns:
            List of DecisionLink that need syncing (synced_version < current_version or NULL).
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, decision_id, jira_key, field_path, linked_at, linked_by, synced_version, synced_at
                FROM decision_links
                WHERE decision_id = %s
                  AND (synced_version IS NULL OR synced_version < %s)
                ORDER BY linked_at DESC
                """,
                (decision_id, current_version),
            )
            rows = await cur.fetchall()

        return [self._row_to_link(row) for row in rows]

    async def get_links_by_field_path(
        self,
        jira_key: str,
        field_path: JiraFieldPath,
    ) -> list[DecisionLink]:
        """Get links for a specific field path on a ticket.

        Useful for finding which decisions affect a specific section
        of a Jira ticket's description.

        Args:
            jira_key: Jira issue key.
            field_path: The field path to filter by.

        Returns:
            List of DecisionLink for that field path.
        """
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, decision_id, jira_key, field_path, linked_at, linked_by, synced_version, synced_at
                FROM decision_links
                WHERE jira_key = %s AND field_path = %s
                ORDER BY linked_at DESC
                """,
                (jira_key, field_path.value),
            )
            rows = await cur.fetchall()

        return [self._row_to_link(row) for row in rows]
