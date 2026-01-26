"""Triage answers store for persisting collected triage context (Phase 44).

Persists triage answers per thread to track what context has been collected
during the questions-first triage stage. Enables:
- Avoiding re-asking questions that have been answered
- Enriching intent classification with collected hints
- Resuming triage conversations across bot restarts
"""
from datetime import datetime, timezone
from typing import Optional
import logging

from psycopg import AsyncConnection

from src.schemas.state import TriageAnswers

logger = logging.getLogger(__name__)


class TriageStore:
    """Store and query triage answers per thread.

    Similar to AnsweredQuestionsStore but for structured triage context
    rather than individual question/answer pairs.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create triage_answers table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS triage_answers (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    mode_hint TEXT,
                    target_hint TEXT,
                    scope_hint TEXT,
                    topic TEXT,
                    clarification TEXT,
                    jira_key TEXT,
                    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(channel_id, thread_ts)
                )
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_triage_answers_thread
                ON triage_answers(channel_id, thread_ts)
            """)
            await self._conn.commit()

    async def get(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[TriageAnswers]:
        """Get triage answers for a thread.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            TriageAnswers if found, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT mode_hint, target_hint, scope_hint, topic,
                       clarification, jira_key, collected_at
                FROM triage_answers
                WHERE channel_id = %s AND thread_ts = %s
            """, (channel_id, thread_ts))
            row = await cur.fetchone()

        if not row:
            return None

        return TriageAnswers(
            mode_hint=row[0],
            target_hint=row[1],
            scope_hint=row[2],
            topic=row[3],
            clarification=row[4],
            jira_key=row[5],
            collected_at=row[6],
            collected_in_thread=thread_ts,
        )

    async def save(
        self,
        channel_id: str,
        thread_ts: str,
        answers: TriageAnswers,
    ) -> None:
        """Save or update triage answers (upsert).

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            answers: TriageAnswers to persist
        """
        now = datetime.now(timezone.utc)

        try:
            async with self._conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO triage_answers
                        (channel_id, thread_ts, mode_hint, target_hint, scope_hint,
                         topic, clarification, jira_key, collected_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (channel_id, thread_ts)
                    DO UPDATE SET
                        mode_hint = EXCLUDED.mode_hint,
                        target_hint = EXCLUDED.target_hint,
                        scope_hint = EXCLUDED.scope_hint,
                        topic = EXCLUDED.topic,
                        clarification = EXCLUDED.clarification,
                        jira_key = EXCLUDED.jira_key,
                        collected_at = EXCLUDED.collected_at
                """, (
                    channel_id,
                    thread_ts,
                    answers.mode_hint,
                    answers.target_hint,
                    answers.scope_hint,
                    answers.topic,
                    answers.clarification,
                    answers.jira_key,
                    answers.collected_at or now,
                ))
                await self._conn.commit()

            logger.info(
                "Saved triage answers",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "mode_hint": answers.mode_hint,
                    "target_hint": answers.target_hint,
                },
            )
        except Exception as e:
            logger.error(f"Failed to save triage answers: {e}")
            raise

    async def update_field(
        self,
        channel_id: str,
        thread_ts: str,
        field: str,
        value: str,
    ) -> TriageAnswers:
        """Update a single field and return updated answers.

        Allows incremental answer collection as user clicks buttons
        or provides responses. Creates a new record if none exists.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            field: Field name to update (mode_hint, target_hint, etc.)
            value: New value for the field

        Returns:
            Updated TriageAnswers

        Raises:
            ValueError: If field is not a valid TriageAnswers field
        """
        valid_fields = {
            "mode_hint", "target_hint", "scope_hint",
            "topic", "clarification", "jira_key"
        }
        if field not in valid_fields:
            raise ValueError(f"Invalid field: {field}. Must be one of {valid_fields}")

        now = datetime.now(timezone.utc)

        try:
            async with self._conn.cursor() as cur:
                # Use dynamic SQL safely with validated field name
                await cur.execute(f"""
                    INSERT INTO triage_answers
                        (channel_id, thread_ts, {field}, collected_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (channel_id, thread_ts)
                    DO UPDATE SET
                        {field} = EXCLUDED.{field},
                        collected_at = EXCLUDED.collected_at
                    RETURNING mode_hint, target_hint, scope_hint, topic,
                              clarification, jira_key, collected_at
                """, (channel_id, thread_ts, value, now))

                row = await cur.fetchone()
                await self._conn.commit()

            logger.info(
                "Updated triage answer field",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "field": field,
                    "value": value,
                },
            )

            return TriageAnswers(
                mode_hint=row[0],
                target_hint=row[1],
                scope_hint=row[2],
                topic=row[3],
                clarification=row[4],
                jira_key=row[5],
                collected_at=row[6],
                collected_in_thread=thread_ts,
            )
        except Exception as e:
            logger.error(f"Failed to update triage answer field: {e}")
            raise

    async def clear(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Clear triage answers for a thread.

        Useful when thread changes topic or user wants to start fresh.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            True if a record was deleted, False if none existed
        """
        try:
            async with self._conn.cursor() as cur:
                await cur.execute("""
                    DELETE FROM triage_answers
                    WHERE channel_id = %s AND thread_ts = %s
                """, (channel_id, thread_ts))
                deleted = cur.rowcount > 0
                await self._conn.commit()

            if deleted:
                logger.info(
                    "Cleared triage answers for thread",
                    extra={
                        "channel_id": channel_id,
                        "thread_ts": thread_ts,
                    },
                )

            return deleted
        except Exception as e:
            logger.error(f"Failed to clear triage answers: {e}")
            raise
