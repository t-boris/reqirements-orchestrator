"""Open question tracking for no-response policy.

Tracks questions that went unanswered to prevent infinite ping loops.
After MAX_PINGS unanswered attempts, questions are logged as "OPEN QUESTION"
and the bot stops pinging.

Key behaviors:
- Record questions when asked
- Track ping count (increment on retry)
- Stop pinging after MAX_PINGS (default: 3)
- Mark answered when resolved

Phase 27.6 - Notifications & Slack UX
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from pydantic import BaseModel, Field
from psycopg import AsyncConnection


class OpenQuestion(BaseModel):
    """A question that went unanswered and was logged."""

    question_id: str = Field(description="UUID")
    channel_id: str
    thread_ts: str
    question_text: str = Field(description="The question asked")
    target_user_ids: list[str] = Field(description="Users who were asked")
    ping_count: int = Field(default=1, description="Number of times asked")
    last_ping_at: datetime
    status: str = Field(default="open", description="open, answered, closed")
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None


class OpenQuestionStore:
    """Track unanswered questions to prevent infinite loops.

    Usage:
        async with get_connection() as conn:
            store = OpenQuestionStore(conn)
            await store.ensure_table()

            # Before pinging, check if we should
            if await store.should_ping_again(channel_id, thread_ts):
                # Send the ping
                await store.record_question(channel_id, thread_ts, question, [user_id])
            else:
                # Already at max pings, don't spam
                pass
    """

    MAX_PINGS = 3

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create open_questions table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS open_questions (
                    question_id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    question_text TEXT NOT NULL,
                    target_user_ids TEXT[] NOT NULL,
                    ping_count INT DEFAULT 1,
                    last_ping_at TIMESTAMPTZ NOT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMPTZ NOT NULL,
                    resolved_at TIMESTAMPTZ,
                    resolved_by TEXT
                )
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_open_questions_thread
                ON open_questions(channel_id, thread_ts)
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_open_questions_status
                ON open_questions(status)
                WHERE status = 'open'
            """)
            await self._conn.commit()

    async def record_question(
        self,
        channel_id: str,
        thread_ts: str,
        question_text: str,
        target_user_ids: list[str],
    ) -> OpenQuestion:
        """Record a new question or increment ping count.

        If an open question already exists in this thread, increments ping_count.
        Otherwise creates a new question record.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            question_text: The question being asked
            target_user_ids: Users being asked

        Returns:
            OpenQuestion with current state (new or updated)
        """
        now = datetime.now(timezone.utc)

        # Check if similar question exists in this thread
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM open_questions
                WHERE channel_id = %s AND thread_ts = %s AND status = 'open'
                ORDER BY created_at DESC LIMIT 1
            """, (channel_id, thread_ts))
            existing = await cur.fetchone()

        if existing:
            # Increment ping count on existing question
            question_id = str(existing[0])
            ping_count = existing[5] + 1
            async with self._conn.cursor() as cur:
                await cur.execute("""
                    UPDATE open_questions
                    SET ping_count = %s, last_ping_at = %s, question_text = %s
                    WHERE question_id = %s
                    RETURNING *
                """, (ping_count, now, question_text, question_id))
                row = await cur.fetchone()
                await self._conn.commit()
            return self._row_to_model(row)

        # Create new question
        question_id = str(uuid.uuid4())
        async with self._conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO open_questions
                    (question_id, channel_id, thread_ts, question_text, target_user_ids,
                     ping_count, last_ping_at, status, created_at)
                VALUES (%s, %s, %s, %s, %s, 1, %s, 'open', %s)
                RETURNING *
            """, (question_id, channel_id, thread_ts, question_text, target_user_ids, now, now))
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_model(row)

    async def should_ping_again(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Check if we should ping again (under MAX_PINGS).

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            True if ping count is under MAX_PINGS (or no prior question)
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT ping_count FROM open_questions
                WHERE channel_id = %s AND thread_ts = %s AND status = 'open'
                ORDER BY created_at DESC LIMIT 1
            """, (channel_id, thread_ts))
            row = await cur.fetchone()

        if not row:
            return True  # No prior question, ok to ping

        return row[0] < self.MAX_PINGS

    async def get_ping_count(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> int:
        """Get current ping count for a thread's open question.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            Current ping count (0 if no open question)
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT ping_count FROM open_questions
                WHERE channel_id = %s AND thread_ts = %s AND status = 'open'
                ORDER BY created_at DESC LIMIT 1
            """, (channel_id, thread_ts))
            row = await cur.fetchone()

        return row[0] if row else 0

    async def mark_answered(
        self,
        channel_id: str,
        thread_ts: str,
        answered_by: str,
    ) -> None:
        """Mark questions in thread as answered.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            answered_by: User ID who answered
        """
        now = datetime.now(timezone.utc)
        async with self._conn.cursor() as cur:
            await cur.execute("""
                UPDATE open_questions
                SET status = 'answered', resolved_at = %s, resolved_by = %s
                WHERE channel_id = %s AND thread_ts = %s AND status = 'open'
            """, (now, answered_by, channel_id, thread_ts))
            await self._conn.commit()

    async def mark_closed(
        self,
        channel_id: str,
        thread_ts: str,
        reason: str = "max_pings_reached",
    ) -> None:
        """Mark questions as closed (no longer following up).

        Used when MAX_PINGS is reached or question is no longer relevant.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            reason: Why question was closed
        """
        now = datetime.now(timezone.utc)
        async with self._conn.cursor() as cur:
            await cur.execute("""
                UPDATE open_questions
                SET status = 'closed', resolved_at = %s
                WHERE channel_id = %s AND thread_ts = %s AND status = 'open'
            """, (now, channel_id, thread_ts))
            await self._conn.commit()

    async def get_open_questions(
        self,
        channel_id: str,
        limit: int = 10,
    ) -> list[OpenQuestion]:
        """Get open questions for a channel.

        Args:
            channel_id: Slack channel ID
            limit: Maximum questions to return

        Returns:
            List of OpenQuestion objects ordered by last_ping_at DESC
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM open_questions
                WHERE channel_id = %s AND status = 'open'
                ORDER BY last_ping_at DESC LIMIT %s
            """, (channel_id, limit))
            rows = await cur.fetchall()

        return [self._row_to_model(row) for row in rows]

    async def get_question(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[OpenQuestion]:
        """Get the open question for a specific thread.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            OpenQuestion if one exists and is open, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM open_questions
                WHERE channel_id = %s AND thread_ts = %s AND status = 'open'
                ORDER BY created_at DESC LIMIT 1
            """, (channel_id, thread_ts))
            row = await cur.fetchone()

        return self._row_to_model(row) if row else None

    async def get_stale_questions(
        self,
        hours_since_last_ping: int = 24,
        limit: int = 50,
    ) -> list[OpenQuestion]:
        """Get open questions that haven't been pinged recently.

        Useful for batch cleanup or escalation workflows.

        Args:
            hours_since_last_ping: Minimum hours since last ping
            limit: Maximum questions to return

        Returns:
            List of stale OpenQuestion objects
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM open_questions
                WHERE status = 'open'
                  AND last_ping_at < NOW() - INTERVAL '%s hours'
                ORDER BY last_ping_at ASC LIMIT %s
            """, (hours_since_last_ping, limit))
            rows = await cur.fetchall()

        return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row: tuple) -> OpenQuestion:
        """Convert database row to OpenQuestion model."""
        return OpenQuestion(
            question_id=str(row[0]),
            channel_id=row[1],
            thread_ts=row[2],
            question_text=row[3],
            target_user_ids=list(row[4]) if row[4] else [],
            ping_count=row[5],
            last_ping_at=row[6],
            status=row[7],
            created_at=row[8],
            resolved_at=row[9],
            resolved_by=row[10],
        )
