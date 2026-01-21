"""Jira Registry Store for channel-level Jira issue ownership.

Implements Rule 8: Channel explicitly owns list of Jira issues.
Queryable registry per channel, not scattered across stores.

Link types:
- owned: Created from this channel, channel is primary owner
- tracked: Explicitly tracked via /maro track command
- mentioned: Referenced in discussions, not actively tracked
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


LinkType = Literal["owned", "tracked", "mentioned"]


@dataclass
class JiraIssueLink:
    """A Jira issue linked to a channel."""

    id: str
    channel_id: str
    jira_key: str
    workitem_id: Optional[str]  # If linked to WorkItem
    link_type: LinkType
    linked_at: datetime
    linked_by: str


class JiraRegistryStore:
    """Store for channel → Jira issue registry.

    Central registry for all Jira issues linked to each channel.
    Replaces scattered tracking across multiple stores.

    Usage:
        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)
            await registry.create_tables()
            await registry.register(channel_id, "SCRUM-123", "owned", user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create jira_registry table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS jira_registry (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    channel_id TEXT NOT NULL,
                    jira_key TEXT NOT NULL,
                    workitem_id UUID,
                    link_type TEXT NOT NULL,
                    linked_at TIMESTAMPTZ NOT NULL,
                    linked_by TEXT NOT NULL,
                    UNIQUE(channel_id, jira_key)
                )
            """)

            # Index for efficient channel lookups
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_jira_registry_channel
                ON jira_registry (channel_id)
            """)

            # Index for efficient key lookups
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_jira_registry_key
                ON jira_registry (jira_key)
            """)

            # Index for workitem lookups
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_jira_registry_workitem
                ON jira_registry (workitem_id)
                WHERE workitem_id IS NOT NULL
            """)

            await self._conn.commit()

    def _row_to_link(self, row: tuple) -> JiraIssueLink:
        """Convert database row to JiraIssueLink.

        Args:
            row: Tuple from database query with columns:
                 id, channel_id, jira_key, workitem_id, link_type, linked_at, linked_by

        Returns:
            JiraIssueLink dataclass instance.
        """
        return JiraIssueLink(
            id=str(row[0]),
            channel_id=row[1],
            jira_key=row[2],
            workitem_id=str(row[3]) if row[3] else None,
            link_type=row[4],
            linked_at=row[5],
            linked_by=row[6],
        )

    async def register(
        self,
        channel_id: str,
        jira_key: str,
        link_type: LinkType,
        linked_by: str,
        workitem_id: Optional[str] = None,
    ) -> JiraIssueLink:
        """Register a Jira issue in a channel's registry.

        Uses UPSERT - if already registered, updates link_type and linked_by.

        Args:
            channel_id: Slack channel ID.
            jira_key: Jira issue key (e.g., "SCRUM-123").
            link_type: Type of link (owned, tracked, mentioned).
            linked_by: Slack user ID who triggered registration.
            workitem_id: Optional WorkItem UUID if linked to WorkItem.

        Returns:
            JiraIssueLink: The registered link record.
        """
        now = datetime.now(timezone.utc)
        # Normalize issue key to uppercase
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO jira_registry (
                    channel_id, jira_key, workitem_id, link_type, linked_at, linked_by
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (channel_id, jira_key) DO UPDATE SET
                    link_type = EXCLUDED.link_type,
                    linked_at = EXCLUDED.linked_at,
                    linked_by = EXCLUDED.linked_by,
                    workitem_id = COALESCE(EXCLUDED.workitem_id, jira_registry.workitem_id)
                RETURNING id, channel_id, jira_key, workitem_id, link_type, linked_at, linked_by
                """,
                (channel_id, jira_key, workitem_id, link_type, now, linked_by),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        logger.info(
            "Jira issue registered in channel",
            extra={
                "channel_id": channel_id,
                "jira_key": jira_key,
                "link_type": link_type,
                "linked_by": linked_by,
            },
        )

        return self._row_to_link(row)

    async def unregister(
        self,
        channel_id: str,
        jira_key: str,
    ) -> bool:
        """Remove a Jira issue from a channel's registry.

        Args:
            channel_id: Slack channel ID.
            jira_key: Jira issue key.

        Returns:
            True if issue was registered and removed, False if not found.
        """
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM jira_registry
                WHERE channel_id = %s AND jira_key = %s
                RETURNING jira_key
                """,
                (channel_id, jira_key),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if row:
            logger.info(
                "Jira issue unregistered from channel",
                extra={
                    "channel_id": channel_id,
                    "jira_key": jira_key,
                },
            )
            return True

        return False

    async def get_channel_issues(
        self,
        channel_id: str,
        limit: int = 100,
    ) -> list[JiraIssueLink]:
        """Get all Jira issues registered in a channel.

        Args:
            channel_id: Slack channel ID.
            limit: Maximum issues to return.

        Returns:
            List of JiraIssueLink ordered by linked_at descending.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, jira_key, workitem_id, link_type, linked_at, linked_by
                FROM jira_registry
                WHERE channel_id = %s
                ORDER BY linked_at DESC
                LIMIT %s
                """,
                (channel_id, limit),
            )
            rows = await cur.fetchall()

        return [self._row_to_link(row) for row in rows]

    async def get_by_type(
        self,
        channel_id: str,
        link_type: LinkType,
        limit: int = 100,
    ) -> list[JiraIssueLink]:
        """Get Jira issues by link type for a channel.

        Args:
            channel_id: Slack channel ID.
            link_type: Type of link to filter by.
            limit: Maximum issues to return.

        Returns:
            List of JiraIssueLink with specified type.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, jira_key, workitem_id, link_type, linked_at, linked_by
                FROM jira_registry
                WHERE channel_id = %s AND link_type = %s
                ORDER BY linked_at DESC
                LIMIT %s
                """,
                (channel_id, link_type, limit),
            )
            rows = await cur.fetchall()

        return [self._row_to_link(row) for row in rows]

    async def is_registered(
        self,
        channel_id: str,
        jira_key: str,
    ) -> bool:
        """Check if a Jira issue is registered in a channel.

        Args:
            channel_id: Slack channel ID.
            jira_key: Jira issue key.

        Returns:
            True if registered, False otherwise.
        """
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1 FROM jira_registry
                WHERE channel_id = %s AND jira_key = %s
                """,
                (channel_id, jira_key),
            )
            row = await cur.fetchone()

        return row is not None

    async def get_link(
        self,
        channel_id: str,
        jira_key: str,
    ) -> Optional[JiraIssueLink]:
        """Get a specific registry link.

        Args:
            channel_id: Slack channel ID.
            jira_key: Jira issue key.

        Returns:
            JiraIssueLink if found, None otherwise.
        """
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, jira_key, workitem_id, link_type, linked_at, linked_by
                FROM jira_registry
                WHERE channel_id = %s AND jira_key = %s
                """,
                (channel_id, jira_key),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_link(row)

    async def get_channels_for_issue(
        self,
        jira_key: str,
    ) -> list[JiraIssueLink]:
        """Get all channels that have registered a Jira issue.

        Useful for finding which channels care about an issue for notifications.

        Args:
            jira_key: Jira issue key.

        Returns:
            List of JiraIssueLink from all channels.
        """
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, jira_key, workitem_id, link_type, linked_at, linked_by
                FROM jira_registry
                WHERE jira_key = %s
                ORDER BY linked_at DESC
                """,
                (jira_key,),
            )
            rows = await cur.fetchall()

        return [self._row_to_link(row) for row in rows]

    async def update_workitem_link(
        self,
        channel_id: str,
        jira_key: str,
        workitem_id: str,
    ) -> Optional[JiraIssueLink]:
        """Update the WorkItem link for a registered issue.

        Args:
            channel_id: Slack channel ID.
            jira_key: Jira issue key.
            workitem_id: WorkItem UUID to link.

        Returns:
            Updated JiraIssueLink if found, None otherwise.
        """
        jira_key = jira_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE jira_registry
                SET workitem_id = %s
                WHERE channel_id = %s AND jira_key = %s
                RETURNING id, channel_id, jira_key, workitem_id, link_type, linked_at, linked_by
                """,
                (workitem_id, channel_id, jira_key),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            return None

        return self._row_to_link(row)

    async def get_owned_count(self, channel_id: str) -> int:
        """Get count of owned issues in a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Count of issues with link_type='owned'.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) FROM jira_registry
                WHERE channel_id = %s AND link_type = 'owned'
                """,
                (channel_id,),
            )
            row = await cur.fetchone()

        return row[0] if row else 0

    async def get_tracked_count(self, channel_id: str) -> int:
        """Get count of tracked issues in a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Count of issues with link_type='tracked'.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) FROM jira_registry
                WHERE channel_id = %s AND link_type = 'tracked'
                """,
                (channel_id,),
            )
            row = await cur.fetchone()

        return row[0] if row else 0
