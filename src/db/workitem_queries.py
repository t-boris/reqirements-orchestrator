"""WorkItem queries module for complex query operations.

Provides specialized query methods for WorkItems.
Split from workitem_store.py for modularization.
"""
from typing import Any, Literal

from psycopg import AsyncConnection

from src.db.models import WorkItem, WorkItemStatus, WorkItemType


class WorkItemQueries:
    """Query operations for WorkItems.

    Handles complex queries including filtering, user lookups,
    and canonical message lookups.

    Usage:
        async with get_connection() as conn:
            queries = WorkItemQueries(conn)
            items = await queries.list_by_channel(channel_id, status=[WorkItemStatus.DRAFT])
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize queries with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def list_by_channel(
        self,
        channel_id: str,
        *,
        status: list[WorkItemStatus] | None = None,
        item_type: WorkItemType | None = None,
        limit: int = 20,
    ) -> list[WorkItem]:
        """List work items for a channel with optional filters.

        Args:
            channel_id: Slack channel ID.
            status: Optional list of statuses to filter by.
            item_type: Optional type filter.
            limit: Maximum items to return.

        Returns:
            List of WorkItem objects, ordered by updated_at DESC.
        """
        query = """
            SELECT id, channel_id, item_type, status, summary, description,
                   facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                   source_thread_ts, created_by, created_at, updated_at,
                   owners, watchers, last_updated_by, readiness_score,
                   canonical_message_ts, canonical_channel_id
            FROM work_items
            WHERE channel_id = %s
        """
        params: list[Any] = [channel_id]

        if status is not None:
            status_values = [s.value for s in status]
            placeholders = ", ".join(["%s"] * len(status_values))
            query += f" AND status IN ({placeholders})"
            params.extend(status_values)

        if item_type is not None:
            query += " AND item_type = %s"
            params.append(item_type.value)

        query += " ORDER BY updated_at DESC LIMIT %s"
        params.append(limit)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_workitem(row) for row in rows]

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
                       source_thread_ts, created_by, created_at, updated_at,
                       owners, watchers, last_updated_by, readiness_score,
                       canonical_message_ts, canonical_channel_id
                FROM work_items
                WHERE jira_key = %s
                """,
                (jira_key,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_workitem(row)

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
                       source_thread_ts, created_by, created_at, updated_at,
                       owners, watchers, last_updated_by, readiness_score,
                       canonical_message_ts, canonical_channel_id
                FROM work_items
                WHERE parent_id = %s
                ORDER BY created_at DESC
                """,
                (parent_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_workitem(row) for row in rows]

    async def get_items_for_user(
        self,
        channel_id: str,
        user_id: str,
        role: Literal["owner", "watcher", "any"] = "any",
    ) -> list[WorkItem]:
        """Get work items where user is owner or watcher.

        Args:
            channel_id: Slack channel ID.
            user_id: User ID to search for.
            role: Filter by role - "owner", "watcher", or "any" (default).

        Returns:
            List of WorkItem objects where user has the specified role.
        """
        if role == "owner":
            where_clause = "channel_id = %s AND %s = ANY(owners)"
        elif role == "watcher":
            where_clause = "channel_id = %s AND %s = ANY(watchers)"
        else:  # any
            where_clause = "channel_id = %s AND (%s = ANY(owners) OR %s = ANY(watchers))"

        query = f"""
            SELECT id, channel_id, item_type, status, summary, description,
                   facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                   source_thread_ts, created_by, created_at, updated_at,
                   owners, watchers, last_updated_by, readiness_score,
                   canonical_message_ts, canonical_channel_id
            FROM work_items
            WHERE {where_clause}
            ORDER BY updated_at DESC
        """

        if role == "any":
            params = (channel_id, user_id, user_id)
        else:
            params = (channel_id, user_id)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_workitem(row) for row in rows]

    async def get_by_canonical_message(
        self,
        channel_id: str,
        message_ts: str,
    ) -> WorkItem | None:
        """Lookup WorkItem by its canonical message.

        Use case: When user posts in thread under WorkItem anchor,
        we need to know which WorkItem they're interacting with.

        Args:
            channel_id: Slack channel ID.
            message_ts: Message timestamp (parent message ts for thread).

        Returns:
            WorkItem if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, item_type, status, summary, description,
                       facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                       source_thread_ts, created_by, created_at, updated_at,
                       owners, watchers, last_updated_by, readiness_score,
                       canonical_message_ts, canonical_channel_id
                FROM work_items
                WHERE canonical_channel_id = %s
                  AND canonical_message_ts = %s
                """,
                (channel_id, message_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_workitem(row)

    async def list_by_status(
        self,
        channel_id: str,
        status: WorkItemStatus,
        *,
        limit: int = 50,
    ) -> list[WorkItem]:
        """List work items by status in a channel.

        Args:
            channel_id: Slack channel ID.
            status: Status to filter by.
            limit: Maximum items to return.

        Returns:
            List of WorkItem objects with the specified status.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, item_type, status, summary, description,
                       facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                       source_thread_ts, created_by, created_at, updated_at,
                       owners, watchers, last_updated_by, readiness_score,
                       canonical_message_ts, canonical_channel_id
                FROM work_items
                WHERE channel_id = %s AND status = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (channel_id, status.value, limit),
            )
            rows = await cur.fetchall()

        return [self._row_to_workitem(row) for row in rows]

    async def count_by_channel(self, channel_id: str) -> dict[str, int]:
        """Count work items by status in a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Dict mapping status values to counts.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT status, COUNT(*) as count
                FROM work_items
                WHERE channel_id = %s
                GROUP BY status
                """,
                (channel_id,),
            )
            rows = await cur.fetchall()

        return {row[0]: row[1] for row in rows}

    def _row_to_workitem(self, row: tuple) -> WorkItem:
        """Convert database row to WorkItem model.

        Args:
            row: Tuple from database query.
                Expected order (21 columns):
                0: id, 1: channel_id, 2: item_type, 3: status,
                4: summary, 5: description, 6: facts,
                7: jira_key, 8: jira_sync_at, 9: jira_fingerprint,
                10: parent_id, 11: source_thread_ts, 12: created_by,
                13: created_at, 14: updated_at,
                15: owners, 16: watchers, 17: last_updated_by,
                18: readiness_score,
                19: canonical_message_ts, 20: canonical_channel_id

        Returns:
            WorkItem model instance.
        """
        # Parse JSONB fields
        facts = row[6] if row[6] else {}
        jira_fingerprint = row[9] if row[9] else None
        # Parse ownership arrays (may be None for older records)
        owners = list(row[15]) if row[15] else []
        watchers = list(row[16]) if row[16] else []
        last_updated_by = row[17] if row[17] else None

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
            owners=owners,
            watchers=watchers,
            last_updated_by=last_updated_by,
            readiness_score=row[18],
            canonical_message_ts=row[19] if row[19] else None,
            canonical_channel_id=row[20] if row[20] else None,
        )
