"""WorkItem store with async CRUD operations using psycopg v3.

Provides database persistence for work items in the channel registry.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from psycopg import AsyncConnection

from src.db.models import WorkItem, WorkItemStatus, WorkItemType


class WorkItemStore:
    """Async CRUD operations for WorkItems.

    Usage:
        async with get_connection() as conn:
            store = WorkItemStore(conn)
            item = await store.create(channel_id, WorkItemType.STORY, "Add retry logic", user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create work_items table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS work_items (
                    id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',

                    -- Content
                    summary TEXT NOT NULL,
                    description TEXT,
                    facts JSONB DEFAULT '{}',

                    -- Jira linkage
                    jira_key TEXT,
                    jira_sync_at TIMESTAMPTZ,
                    jira_fingerprint JSONB,

                    -- Hierarchy
                    parent_id UUID,

                    -- Provenance
                    source_thread_ts TEXT,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),

                    -- Readiness
                    readiness_score REAL DEFAULT 0.0
                )
            """)

            # Index on channel_id for list queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_work_items_channel_id
                ON work_items(channel_id)
            """)

            # Index on jira_key for sync lookups
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_work_items_jira_key
                ON work_items(jira_key)
                WHERE jira_key IS NOT NULL
            """)

            # Index on parent_id for hierarchy queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_work_items_parent_id
                ON work_items(parent_id)
                WHERE parent_id IS NOT NULL
            """)

            await self._conn.commit()

    async def create(
        self,
        channel_id: str,
        item_type: WorkItemType,
        summary: str,
        created_by: str,
        *,
        description: str | None = None,
        parent_id: str | None = None,
        source_thread_ts: str | None = None,
    ) -> WorkItem:
        """Create a new draft work item.

        Args:
            channel_id: Slack channel ID.
            item_type: Type of work item (EPIC, STORY, etc.).
            summary: Title/summary of the work item.
            created_by: User ID who created the item.
            description: Optional full description.
            parent_id: Optional parent WorkItem UUID.
            source_thread_ts: Optional thread timestamp that created this item.

        Returns:
            WorkItem: Newly created work item with DRAFT status.
        """
        item_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO work_items (
                    id, channel_id, item_type, status, summary, description,
                    parent_id, source_thread_ts, created_by, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, channel_id, item_type, status, summary, description,
                          facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                          source_thread_ts, created_by, created_at, updated_at, readiness_score
                """,
                (
                    item_id,
                    channel_id,
                    item_type.value,
                    WorkItemStatus.DRAFT.value,
                    summary,
                    description,
                    parent_id,
                    source_thread_ts,
                    created_by,
                    now,
                    now,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_workitem(row)

    async def get(self, item_id: str) -> WorkItem | None:
        """Get work item by ID.

        Args:
            item_id: UUID of the work item.

        Returns:
            WorkItem if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, item_type, status, summary, description,
                       facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                       source_thread_ts, created_by, created_at, updated_at, readiness_score
                FROM work_items
                WHERE id = %s
                """,
                (item_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_workitem(row)

    async def get_by_jira_key(self, jira_key: str) -> WorkItem | None:
        """Get work item by Jira key (for sync lookups).

        Args:
            jira_key: Jira issue key (e.g., PROJ-123).

        Returns:
            WorkItem if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, item_type, status, summary, description,
                       facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                       source_thread_ts, created_by, created_at, updated_at, readiness_score
                FROM work_items
                WHERE jira_key = %s
                """,
                (jira_key,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_workitem(row)

    async def list_by_channel(
        self,
        channel_id: str,
        *,
        status: WorkItemStatus | None = None,
        item_type: WorkItemType | None = None,
    ) -> list[WorkItem]:
        """List work items for a channel with optional filters.

        Args:
            channel_id: Slack channel ID.
            status: Optional status filter.
            item_type: Optional type filter.

        Returns:
            List of WorkItem objects, ordered by created_at DESC.
        """
        query = """
            SELECT id, channel_id, item_type, status, summary, description,
                   facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                   source_thread_ts, created_by, created_at, updated_at, readiness_score
            FROM work_items
            WHERE channel_id = %s
        """
        params: list[Any] = [channel_id]

        if status is not None:
            query += " AND status = %s"
            params.append(status.value)

        if item_type is not None:
            query += " AND item_type = %s"
            params.append(item_type.value)

        query += " ORDER BY created_at DESC"

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_workitem(row) for row in rows]

    async def update(
        self,
        item_id: str,
        *,
        summary: str | None = None,
        description: str | None = None,
        status: WorkItemStatus | None = None,
        jira_key: str | None = None,
        jira_sync_at: datetime | None = None,
        jira_fingerprint: dict[str, str] | None = None,
        facts: dict[str, Any] | None = None,
        readiness_score: float | None = None,
    ) -> WorkItem:
        """Update work item fields. Only non-None values are updated.

        Args:
            item_id: UUID of the work item to update.
            summary: New summary if provided.
            description: New description if provided.
            status: New status if provided.
            jira_key: New Jira key if provided.
            jira_sync_at: New sync timestamp if provided.
            jira_fingerprint: New fingerprint if provided.
            facts: New facts dict if provided.
            readiness_score: New readiness score if provided.

        Returns:
            WorkItem: Updated work item.

        Raises:
            ValueError: If work item not found.
        """
        # Build dynamic SET clause
        set_clauses: list[str] = []
        params: list[Any] = []

        if summary is not None:
            set_clauses.append("summary = %s")
            params.append(summary)

        if description is not None:
            set_clauses.append("description = %s")
            params.append(description)

        if status is not None:
            set_clauses.append("status = %s")
            params.append(status.value)

        if jira_key is not None:
            set_clauses.append("jira_key = %s")
            params.append(jira_key)

        if jira_sync_at is not None:
            set_clauses.append("jira_sync_at = %s")
            params.append(jira_sync_at)

        if jira_fingerprint is not None:
            set_clauses.append("jira_fingerprint = %s")
            params.append(json.dumps(jira_fingerprint))

        if facts is not None:
            set_clauses.append("facts = %s")
            params.append(json.dumps(facts))

        if readiness_score is not None:
            set_clauses.append("readiness_score = %s")
            params.append(readiness_score)

        # Always update updated_at
        set_clauses.append("updated_at = %s")
        now = datetime.now(timezone.utc)
        params.append(now)

        # Add item_id for WHERE clause
        params.append(item_id)

        query = f"""
            UPDATE work_items
            SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING id, channel_id, item_type, status, summary, description,
                      facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                      source_thread_ts, created_by, created_at, updated_at, readiness_score
        """

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"WorkItem not found: {item_id}")

        return self._row_to_workitem(row)

    async def delete(self, item_id: str) -> bool:
        """Delete work item.

        Args:
            item_id: UUID of the work item to delete.

        Returns:
            True if deleted, False if not found.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM work_items WHERE id = %s RETURNING id",
                (item_id,),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    async def get_children(self, parent_id: str) -> list[WorkItem]:
        """Get child work items (stories under epic).

        Args:
            parent_id: UUID of the parent work item.

        Returns:
            List of child WorkItem objects, ordered by created_at DESC.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, item_type, status, summary, description,
                       facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                       source_thread_ts, created_by, created_at, updated_at, readiness_score
                FROM work_items
                WHERE parent_id = %s
                ORDER BY created_at DESC
                """,
                (parent_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_workitem(row) for row in rows]

    def _row_to_workitem(self, row: tuple) -> WorkItem:
        """Convert database row to WorkItem model.

        Args:
            row: Tuple from database query.

        Returns:
            WorkItem model instance.
        """
        # Parse JSONB fields
        facts = row[6] if row[6] else {}
        jira_fingerprint = row[9] if row[9] else None

        return WorkItem(
            id=str(row[0]),
            channel_id=row[1],
            item_type=WorkItemType(row[2]),
            status=WorkItemStatus(row[3]),
            summary=row[4],
            description=row[5],
            facts=facts,
            jira_key=row[7],
            jira_sync_at=row[8],
            jira_fingerprint=jira_fingerprint,
            parent_id=str(row[10]) if row[10] else None,
            source_thread_ts=row[11],
            created_by=row[12],
            created_at=row[13],
            updated_at=row[14],
            readiness_score=row[15],
        )
