"""Thread participant tracking for multi-user support.

Tracks who participates in each thread conversation, enabling:
- Mention rules (direct question → mention that user)
- Turn-taking awareness (who's active)
- Multi-user channel coordination

Phase 27.2 - Participant Map & Turn-Taking
"""
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from psycopg import AsyncConnection


class ThreadParticipant(BaseModel):
    """A participant in a thread conversation."""

    channel_id: str = Field(description="Slack channel ID")
    thread_ts: str = Field(description="Thread timestamp")
    user_id: str = Field(description="Slack user ID")
    first_seen_at: datetime = Field(description="When user first participated")
    last_message_at: datetime = Field(description="Most recent message")
    message_count: int = Field(default=1, description="Number of messages in thread")


class ThreadParticipantStore:
    """Track thread participants for multi-user support."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create thread_participants table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS thread_participants (
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    first_seen_at TIMESTAMPTZ NOT NULL,
                    last_message_at TIMESTAMPTZ NOT NULL,
                    message_count INT DEFAULT 1,
                    PRIMARY KEY (channel_id, thread_ts, user_id)
                )
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_thread_participants_thread
                ON thread_participants(channel_id, thread_ts)
            """)
            await self._conn.commit()

    async def record_message(
        self,
        channel_id: str,
        thread_ts: str,
        user_id: str,
    ) -> ThreadParticipant:
        """Record a user's message in a thread. Upsert with message count."""
        now = datetime.now(timezone.utc)
        async with self._conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO thread_participants
                    (channel_id, thread_ts, user_id, first_seen_at, last_message_at, message_count)
                VALUES (%s, %s, %s, %s, %s, 1)
                ON CONFLICT (channel_id, thread_ts, user_id) DO UPDATE SET
                    last_message_at = EXCLUDED.last_message_at,
                    message_count = thread_participants.message_count + 1
                RETURNING *
            """, (channel_id, thread_ts, user_id, now, now))
            row = await cur.fetchone()
            await self._conn.commit()
        return self._row_to_model(row)

    async def get_participants(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> list[ThreadParticipant]:
        """Get all participants in a thread, ordered by message count."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM thread_participants
                WHERE channel_id = %s AND thread_ts = %s
                ORDER BY message_count DESC
            """, (channel_id, thread_ts))
            rows = await cur.fetchall()
        return [self._row_to_model(row) for row in rows]

    async def get_active_participants(
        self,
        channel_id: str,
        thread_ts: str,
        since_minutes: int = 30,
    ) -> list[ThreadParticipant]:
        """Get participants active in the last N minutes."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM thread_participants
                WHERE channel_id = %s AND thread_ts = %s
                  AND last_message_at > NOW() - INTERVAL '%s minutes'
                ORDER BY last_message_at DESC
            """, (channel_id, thread_ts, since_minutes))
            rows = await cur.fetchall()
        return [self._row_to_model(row) for row in rows]

    async def get_participant_count(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> int:
        """Get number of unique participants in a thread."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT COUNT(*) FROM thread_participants
                WHERE channel_id = %s AND thread_ts = %s
            """, (channel_id, thread_ts))
            row = await cur.fetchone()
        return row[0] if row else 0

    async def get_most_active_participant(
        self,
        channel_id: str,
        thread_ts: str,
        exclude_user_id: Optional[str] = None,
    ) -> Optional[ThreadParticipant]:
        """Get the most active participant in a thread.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp
            exclude_user_id: Optional user to exclude (e.g., the bot)

        Returns:
            Most active participant, or None if no participants
        """
        async with self._conn.cursor() as cur:
            if exclude_user_id:
                await cur.execute("""
                    SELECT * FROM thread_participants
                    WHERE channel_id = %s AND thread_ts = %s AND user_id != %s
                    ORDER BY message_count DESC
                    LIMIT 1
                """, (channel_id, thread_ts, exclude_user_id))
            else:
                await cur.execute("""
                    SELECT * FROM thread_participants
                    WHERE channel_id = %s AND thread_ts = %s
                    ORDER BY message_count DESC
                    LIMIT 1
                """, (channel_id, thread_ts))
            row = await cur.fetchone()
        return self._row_to_model(row) if row else None

    async def is_multi_user_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Check if thread has multiple human participants.

        Returns True if more than one unique user has participated.
        Useful for determining if mention rules should apply.
        """
        count = await self.get_participant_count(channel_id, thread_ts)
        return count > 1

    def _row_to_model(self, row: tuple) -> ThreadParticipant:
        """Convert database row to ThreadParticipant model."""
        return ThreadParticipant(
            channel_id=row[0],
            thread_ts=row[1],
            user_id=row[2],
            first_seen_at=row[3],
            last_message_at=row[4],
            message_count=row[5],
        )
