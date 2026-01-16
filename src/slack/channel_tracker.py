"""Channel-level Jira issue tracking store.

Manages channel → Jira issue mappings for sync features.
MARO needs to know which Jira issues are relevant to each channel.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


async def trigger_board_refresh(
    channel_id: str,
    jira_base_url: str = "",
) -> bool:
    """Trigger a board refresh for a channel if a board exists.

    Non-blocking utility that can be called from anywhere to
    refresh the board after issue status changes.

    Args:
        channel_id: Slack channel ID.
        jira_base_url: Base URL for Jira links.

    Returns:
        True if board was refreshed, False otherwise.
    """
    try:
        from src.db import get_connection
        from src.slack.pinned_board import PinnedBoardManager
        from src.slack.app import get_slack_client

        client = get_slack_client()
        if not client:
            logger.debug("No Slack client available for board refresh")
            return False

        async with get_connection() as conn:
            manager = PinnedBoardManager(jira_base_url=jira_base_url)
            return await manager.refresh_if_exists(client, channel_id, conn)

    except Exception as e:
        logger.debug(f"Board refresh trigger failed: {e}")
        return False


@dataclass
class TrackedIssue:
    """A tracked Jira issue in a channel."""

    channel_id: str
    issue_key: str
    tracked_at: datetime
    tracked_by: str  # Slack user ID
    last_synced_at: Optional[datetime] = None
    last_jira_status: Optional[str] = None
    last_jira_summary: Optional[str] = None


class ChannelIssueTracker:
    """Store for channel → Jira issue tracking.

    Tracks which Jira issues are relevant to each channel for sync features.

    Usage:
        async with get_connection() as conn:
            tracker = ChannelIssueTracker(conn)
            await tracker.create_tables()
            await tracker.track(channel_id, "SCRUM-123", user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize tracker with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create channel_tracked_issues table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS channel_tracked_issues (
                    channel_id TEXT NOT NULL,
                    issue_key TEXT NOT NULL,
                    tracked_at TIMESTAMPTZ NOT NULL,
                    tracked_by TEXT NOT NULL,
                    last_synced_at TIMESTAMPTZ,
                    last_jira_status TEXT,
                    last_jira_summary TEXT,
                    PRIMARY KEY (channel_id, issue_key)
                )
            """)
            # Index for efficient channel lookups
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_channel_tracked_issues_channel
                ON channel_tracked_issues (channel_id)
            """)
            await self._conn.commit()

    def _row_to_tracked_issue(self, row: tuple) -> TrackedIssue:
        """Convert database row to TrackedIssue.

        Args:
            row: Tuple from database query with columns:
                 channel_id, issue_key, tracked_at, tracked_by,
                 last_synced_at, last_jira_status, last_jira_summary

        Returns:
            TrackedIssue: Parsed dataclass instance.
        """
        return TrackedIssue(
            channel_id=row[0],
            issue_key=row[1],
            tracked_at=row[2],
            tracked_by=row[3],
            last_synced_at=row[4],
            last_jira_status=row[5],
            last_jira_summary=row[6],
        )

    async def track(
        self,
        channel_id: str,
        issue_key: str,
        tracked_by: str,
    ) -> TrackedIssue:
        """Add issue to channel's tracked list.

        Uses UPSERT - if already tracked, updates tracked_at and tracked_by.

        Args:
            channel_id: Slack channel ID.
            issue_key: Jira issue key (e.g., "SCRUM-123").
            tracked_by: Slack user ID who triggered tracking.

        Returns:
            TrackedIssue: The tracked issue record.
        """
        now = datetime.now(timezone.utc)
        # Normalize issue key to uppercase
        issue_key = issue_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO channel_tracked_issues (
                    channel_id, issue_key, tracked_at, tracked_by
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (channel_id, issue_key) DO UPDATE SET
                    tracked_at = EXCLUDED.tracked_at,
                    tracked_by = EXCLUDED.tracked_by
                RETURNING channel_id, issue_key, tracked_at, tracked_by,
                          last_synced_at, last_jira_status, last_jira_summary
                """,
                (channel_id, issue_key, now, tracked_by),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        logger.info(
            "Issue tracked in channel",
            extra={
                "channel_id": channel_id,
                "issue_key": issue_key,
                "tracked_by": tracked_by,
            },
        )

        return self._row_to_tracked_issue(row)

    async def untrack(
        self,
        channel_id: str,
        issue_key: str,
    ) -> bool:
        """Remove issue from channel's tracked list.

        Args:
            channel_id: Slack channel ID.
            issue_key: Jira issue key.

        Returns:
            True if issue was tracked and removed, False if not found.
        """
        issue_key = issue_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM channel_tracked_issues
                WHERE channel_id = %s AND issue_key = %s
                RETURNING issue_key
                """,
                (channel_id, issue_key),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if row:
            logger.info(
                "Issue untracked from channel",
                extra={
                    "channel_id": channel_id,
                    "issue_key": issue_key,
                },
            )
            return True

        return False

    async def get_tracked_issues(
        self,
        channel_id: str,
    ) -> list[TrackedIssue]:
        """Get all tracked issues for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            List of TrackedIssue ordered by tracked_at descending.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT channel_id, issue_key, tracked_at, tracked_by,
                       last_synced_at, last_jira_status, last_jira_summary
                FROM channel_tracked_issues
                WHERE channel_id = %s
                ORDER BY tracked_at DESC
                """,
                (channel_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_tracked_issue(row) for row in rows]

    async def is_tracked(
        self,
        channel_id: str,
        issue_key: str,
    ) -> bool:
        """Check if an issue is tracked in a channel.

        Args:
            channel_id: Slack channel ID.
            issue_key: Jira issue key.

        Returns:
            True if tracked, False otherwise.
        """
        issue_key = issue_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1 FROM channel_tracked_issues
                WHERE channel_id = %s AND issue_key = %s
                """,
                (channel_id, issue_key),
            )
            row = await cur.fetchone()

        return row is not None

    async def update_sync_status(
        self,
        channel_id: str,
        issue_key: str,
        status: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Optional[TrackedIssue]:
        """Update sync status for a tracked issue.

        Args:
            channel_id: Slack channel ID.
            issue_key: Jira issue key.
            status: Jira issue status (e.g., "In Progress").
            summary: Jira issue summary/title.

        Returns:
            Updated TrackedIssue if found, None otherwise.
        """
        now = datetime.now(timezone.utc)
        issue_key = issue_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_tracked_issues
                SET last_synced_at = %s,
                    last_jira_status = COALESCE(%s, last_jira_status),
                    last_jira_summary = COALESCE(%s, last_jira_summary)
                WHERE channel_id = %s AND issue_key = %s
                RETURNING channel_id, issue_key, tracked_at, tracked_by,
                          last_synced_at, last_jira_status, last_jira_summary
                """,
                (now, status, summary, channel_id, issue_key),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            return None

        return self._row_to_tracked_issue(row)

    async def get_tracked_issue(
        self,
        channel_id: str,
        issue_key: str,
    ) -> Optional[TrackedIssue]:
        """Get a specific tracked issue.

        Args:
            channel_id: Slack channel ID.
            issue_key: Jira issue key.

        Returns:
            TrackedIssue if found, None otherwise.
        """
        issue_key = issue_key.upper()

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT channel_id, issue_key, tracked_at, tracked_by,
                       last_synced_at, last_jira_status, last_jira_summary
                FROM channel_tracked_issues
                WHERE channel_id = %s AND issue_key = %s
                """,
                (channel_id, issue_key),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_tracked_issue(row)
