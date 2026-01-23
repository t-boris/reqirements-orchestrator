"""Answered questions store for preventing question repetition (Phase 28.5 - R10).

Persists answered questions per thread to prevent re-asking questions
that the user has already answered directly.

R10: No question repetition after direct answer
"""
from datetime import datetime, timezone
from typing import Optional
import json
import logging

from psycopg import AsyncConnection
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AnsweredQuestion(BaseModel):
    """Record of an answered question."""

    question_key: str  # Normalized question identifier (e.g., "acceptance_criteria")
    original_question: str  # Full question text that was asked
    answer: str  # User's answer
    answered_at: datetime
    answered_by: str  # user_id


class AnsweredQuestionsStore:
    """Store and query answered questions per thread.

    Prevents re-asking questions that users have already answered.
    Uses JSON column in a dedicated table for efficient querying.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create answered_questions table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS answered_questions (
                    id SERIAL PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    question_key TEXT NOT NULL,
                    original_question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    answered_at TIMESTAMPTZ NOT NULL,
                    answered_by TEXT NOT NULL,
                    UNIQUE (channel_id, thread_ts, question_key)
                )
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_answered_questions_thread
                ON answered_questions(channel_id, thread_ts)
            """)
            await self._conn.commit()

    async def record_answer(
        self,
        channel_id: str,
        thread_ts: str,
        question_key: str,
        original_question: str,
        answer: str,
        user_id: str,
    ) -> None:
        """Record an answered question.

        If the same question_key was already answered, updates the answer.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            question_key: Normalized question identifier
            original_question: Full question text that was asked
            answer: User's answer
            user_id: User who answered
        """
        now = datetime.now(timezone.utc)

        try:
            async with self._conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO answered_questions
                        (channel_id, thread_ts, question_key, original_question, answer, answered_at, answered_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (channel_id, thread_ts, question_key)
                    DO UPDATE SET
                        original_question = EXCLUDED.original_question,
                        answer = EXCLUDED.answer,
                        answered_at = EXCLUDED.answered_at,
                        answered_by = EXCLUDED.answered_by
                """, (
                    channel_id,
                    thread_ts,
                    question_key,
                    original_question,
                    answer,
                    now,
                    user_id,
                ))
                await self._conn.commit()

            logger.info(
                "Recorded answered question",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "question_key": question_key,
                    "user_id": user_id,
                },
            )
        except Exception as e:
            logger.error(f"Failed to record answered question: {e}")
            raise

    async def was_answered(
        self,
        channel_id: str,
        thread_ts: str,
        question_key: str,
    ) -> bool:
        """Check if a specific question was already answered.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            question_key: Normalized question identifier

        Returns:
            True if question was answered, False otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM answered_questions
                    WHERE channel_id = %s AND thread_ts = %s AND question_key = %s
                )
            """, (channel_id, thread_ts, question_key))
            row = await cur.fetchone()
        return row[0] if row else False

    async def get_answer(
        self,
        channel_id: str,
        thread_ts: str,
        question_key: str,
    ) -> Optional[AnsweredQuestion]:
        """Get the answer for a specific question.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            question_key: Normalized question identifier

        Returns:
            AnsweredQuestion if found, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT question_key, original_question, answer, answered_at, answered_by
                FROM answered_questions
                WHERE channel_id = %s AND thread_ts = %s AND question_key = %s
            """, (channel_id, thread_ts, question_key))
            row = await cur.fetchone()

        if not row:
            return None

        return AnsweredQuestion(
            question_key=row[0],
            original_question=row[1],
            answer=row[2],
            answered_at=row[3],
            answered_by=row[4],
        )

    async def get_answered(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> list[AnsweredQuestion]:
        """Get all answered questions for a thread.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            List of AnsweredQuestion records, ordered by answered_at
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT question_key, original_question, answer, answered_at, answered_by
                FROM answered_questions
                WHERE channel_id = %s AND thread_ts = %s
                ORDER BY answered_at ASC
            """, (channel_id, thread_ts))
            rows = await cur.fetchall()

        return [
            AnsweredQuestion(
                question_key=row[0],
                original_question=row[1],
                answer=row[2],
                answered_at=row[3],
                answered_by=row[4],
            )
            for row in rows
        ]

    async def filter_unanswered(
        self,
        channel_id: str,
        thread_ts: str,
        questions: list[str],
    ) -> list[str]:
        """Filter out already-answered questions.

        Takes a list of question keys and returns only those
        that haven't been answered yet.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            questions: List of question keys to filter

        Returns:
            List of question keys that haven't been answered
        """
        if not questions:
            return []

        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT question_key FROM answered_questions
                WHERE channel_id = %s AND thread_ts = %s
            """, (channel_id, thread_ts))
            rows = await cur.fetchall()

        answered_keys = {row[0] for row in rows}
        unanswered = [q for q in questions if q not in answered_keys]

        if len(questions) != len(unanswered):
            logger.info(
                "Filtered already-answered questions",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "original_count": len(questions),
                    "filtered_count": len(unanswered),
                    "answered_count": len(questions) - len(unanswered),
                },
            )

        return unanswered

    async def clear_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> int:
        """Clear all answered questions for a thread.

        Useful when starting fresh or resetting a conversation.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            Number of records deleted
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                DELETE FROM answered_questions
                WHERE channel_id = %s AND thread_ts = %s
            """, (channel_id, thread_ts))
            deleted = cur.rowcount
            await self._conn.commit()

        if deleted > 0:
            logger.info(
                "Cleared answered questions for thread",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "deleted_count": deleted,
                },
            )

        return deleted
