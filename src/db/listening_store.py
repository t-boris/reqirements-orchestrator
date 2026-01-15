"""Listening store for channel listening state using psycopg v3.

Provides async CRUD for tracking which channels have listening enabled
and storing rolling conversation summaries.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.db.models import ChannelListeningState


class ListeningStore:
    """Async store for channel listening state.

    Usage:
        async with get_connection() as conn:
            store = ListeningStore(conn)
            await store.enable(team_id, channel_id, user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create channel_listening_state table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS channel_listening_state (
                    team_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT FALSE,
                    enabled_at TIMESTAMPTZ,
                    enabled_by TEXT,
                    summary TEXT,
                    raw_buffer JSONB DEFAULT '[]',
                    last_summary_at TIMESTAMPTZ,
                    PRIMARY KEY (team_id, channel_id)
                )
            """)
            await self._conn.commit()

    def _row_to_state(self, row: tuple) -> ChannelListeningState:
        """Convert database row to ChannelListeningState model.

        Args:
            row: Tuple from database query with columns:
                 team_id, channel_id, enabled, enabled_at, enabled_by,
                 summary, raw_buffer, last_summary_at

        Returns:
            ChannelListeningState: Parsed model instance.
        """
        raw_buffer = row[6] if row[6] else []

        return ChannelListeningState(
            team_id=row[0],
            channel_id=row[1],
            enabled=row[2] or False,
            enabled_at=row[3],
            enabled_by=row[4],
            summary=row[5],
            raw_buffer=raw_buffer,
            last_summary_at=row[7],
        )

    async def get_state(
        self, team_id: str, channel_id: str
    ) -> Optional[ChannelListeningState]:
        """Get listening state for a channel.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.

        Returns:
            ChannelListeningState if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT team_id, channel_id, enabled, enabled_at, enabled_by,
                       summary, raw_buffer, last_summary_at
                FROM channel_listening_state
                WHERE team_id = %s AND channel_id = %s
                """,
                (team_id, channel_id),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_state(row)

    async def enable(
        self, team_id: str, channel_id: str, user_id: str
    ) -> ChannelListeningState:
        """Enable listening for a channel.

        Uses UPSERT to either create or update the state.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.
            user_id: User who enabled listening.

        Returns:
            ChannelListeningState: Updated state.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO channel_listening_state (
                    team_id, channel_id, enabled, enabled_at, enabled_by,
                    summary, raw_buffer, last_summary_at
                )
                VALUES (%s, %s, TRUE, %s, %s, NULL, '[]', NULL)
                ON CONFLICT (team_id, channel_id) DO UPDATE SET
                    enabled = TRUE,
                    enabled_at = %s,
                    enabled_by = %s
                RETURNING team_id, channel_id, enabled, enabled_at, enabled_by,
                          summary, raw_buffer, last_summary_at
                """,
                (team_id, channel_id, now, user_id, now, user_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_state(row)

    async def disable(
        self, team_id: str, channel_id: str
    ) -> Optional[ChannelListeningState]:
        """Disable listening for a channel.

        Clears enabled_at and enabled_by but preserves summary/buffer.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.

        Returns:
            ChannelListeningState if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_listening_state
                SET enabled = FALSE, enabled_at = NULL, enabled_by = NULL
                WHERE team_id = %s AND channel_id = %s
                RETURNING team_id, channel_id, enabled, enabled_at, enabled_by,
                          summary, raw_buffer, last_summary_at
                """,
                (team_id, channel_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            return None

        return self._row_to_state(row)

    async def is_enabled(self, team_id: str, channel_id: str) -> bool:
        """Quick check if listening is enabled.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.

        Returns:
            True if listening is enabled, False otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT enabled
                FROM channel_listening_state
                WHERE team_id = %s AND channel_id = %s
                """,
                (team_id, channel_id),
            )
            row = await cur.fetchone()

        if not row:
            return False

        return row[0] or False

    async def update_summary(
        self,
        team_id: str,
        channel_id: str,
        summary: str,
        raw_buffer: list[dict],
    ) -> Optional[ChannelListeningState]:
        """Update conversation summary and buffer.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.
            summary: Updated rolling summary text.
            raw_buffer: Updated raw message buffer.

        Returns:
            ChannelListeningState if found, None otherwise.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_listening_state
                SET summary = %s, raw_buffer = %s, last_summary_at = %s
                WHERE team_id = %s AND channel_id = %s
                RETURNING team_id, channel_id, enabled, enabled_at, enabled_by,
                          summary, raw_buffer, last_summary_at
                """,
                (summary, json.dumps(raw_buffer), now, team_id, channel_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            return None

        return self._row_to_state(row)

    async def get_summary(
        self, team_id: str, channel_id: str
    ) -> tuple[Optional[str], list[dict]]:
        """Get summary and raw_buffer for a channel.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.

        Returns:
            Tuple of (summary, raw_buffer). Returns (None, []) if not found.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT summary, raw_buffer
                FROM channel_listening_state
                WHERE team_id = %s AND channel_id = %s
                """,
                (team_id, channel_id),
            )
            row = await cur.fetchone()

        if not row:
            return None, []

        summary = row[0]
        raw_buffer = row[1] if row[1] else []

        return summary, raw_buffer
