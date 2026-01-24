"""ReviewStateStore for persisting architecture review state.

Phase 37: Unified Question Engine

Stores ReviewState per thread, enabling conversation continuity
and state management for the Question Engine.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.schemas.review_state import (
    Assumption,
    Constraint,
    OpenQuestion,
    ProposedDecision,
    ReviewState,
    Risk,
)

logger = logging.getLogger(__name__)


class ReviewStateStore:
    """Persistence for ReviewState.

    One ReviewState per thread (channel_id + thread_ts).

    Usage:
        async with get_connection() as conn:
            store = ReviewStateStore(conn)
            state = await store.get_by_thread(channel_id, thread_ts)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create review_state table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS review_state (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    assumptions JSONB DEFAULT '[]',
                    constraints JSONB DEFAULT '[]',
                    risks JSONB DEFAULT '[]',
                    open_questions JSONB DEFAULT '[]',
                    proposed_decisions JSONB DEFAULT '[]',
                    version INTEGER DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(channel_id, thread_ts)
                )
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_review_state_channel
                ON review_state(channel_id)
            """)
            await self._conn.commit()

    async def get_by_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[ReviewState]:
        """Get ReviewState for a thread.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            ReviewState if exists, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, thread_ts, topic,
                       assumptions, constraints, risks,
                       open_questions, proposed_decisions,
                       version, created_at, updated_at
                FROM review_state
                WHERE channel_id = %s AND thread_ts = %s
                """,
                (channel_id, thread_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_model(row)

    async def upsert(self, state: ReviewState) -> ReviewState:
        """Create or update ReviewState.

        Args:
            state: ReviewState to persist

        Returns:
            Updated ReviewState with new version
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO review_state (
                    id, channel_id, thread_ts, topic,
                    assumptions, constraints, risks,
                    open_questions, proposed_decisions,
                    version, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (channel_id, thread_ts)
                DO UPDATE SET
                    topic = EXCLUDED.topic,
                    assumptions = EXCLUDED.assumptions,
                    constraints = EXCLUDED.constraints,
                    risks = EXCLUDED.risks,
                    open_questions = EXCLUDED.open_questions,
                    proposed_decisions = EXCLUDED.proposed_decisions,
                    version = review_state.version + 1,
                    updated_at = EXCLUDED.updated_at
                RETURNING id, channel_id, thread_ts, topic,
                          assumptions, constraints, risks,
                          open_questions, proposed_decisions,
                          version, created_at, updated_at
                """,
                (
                    state.id,
                    state.channel_id,
                    state.thread_ts,
                    state.topic,
                    json.dumps([a.model_dump() for a in state.assumptions]),
                    json.dumps([c.model_dump() for c in state.constraints]),
                    json.dumps([r.model_dump() for r in state.risks]),
                    json.dumps([q.model_dump(mode="json") for q in state.open_questions]),
                    json.dumps([d.model_dump() for d in state.proposed_decisions]),
                    state.version,
                    state.created_at,
                    now,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_model(row)

    async def add_assumption(
        self,
        channel_id: str,
        thread_ts: str,
        assumption: Assumption,
    ) -> Optional[ReviewState]:
        """Add assumption to existing ReviewState.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            assumption: Assumption to add

        Returns:
            Updated ReviewState if exists, None if no state found
        """
        state = await self.get_by_thread(channel_id, thread_ts)
        if not state:
            return None
        state.assumptions.append(assumption)
        return await self.upsert(state)

    async def add_constraint(
        self,
        channel_id: str,
        thread_ts: str,
        constraint: Constraint,
    ) -> Optional[ReviewState]:
        """Add constraint to existing ReviewState.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            constraint: Constraint to add

        Returns:
            Updated ReviewState if exists, None if no state found
        """
        state = await self.get_by_thread(channel_id, thread_ts)
        if not state:
            return None
        state.constraints.append(constraint)
        return await self.upsert(state)

    async def add_risk(
        self,
        channel_id: str,
        thread_ts: str,
        risk: Risk,
    ) -> Optional[ReviewState]:
        """Add risk to existing ReviewState.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            risk: Risk to add

        Returns:
            Updated ReviewState if exists, None if no state found
        """
        state = await self.get_by_thread(channel_id, thread_ts)
        if not state:
            return None
        state.risks.append(risk)
        return await self.upsert(state)

    async def answer_question(
        self,
        channel_id: str,
        thread_ts: str,
        question_id: str,
        answer: str,
    ) -> Optional[ReviewState]:
        """Record answer to open question.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            question_id: ID of question to answer
            answer: The answer text

        Returns:
            Updated ReviewState if exists, None if not found
        """
        state = await self.get_by_thread(channel_id, thread_ts)
        if not state:
            return None

        now = datetime.now(timezone.utc)
        for q in state.open_questions:
            if q.id == question_id:
                q.answer = answer
                q.answered_at = now
                break

        return await self.upsert(state)

    def _row_to_model(self, row: tuple) -> ReviewState:
        """Convert DB row to ReviewState model.

        Args:
            row: Tuple from database query.
                Expected order (12 columns):
                0: id, 1: channel_id, 2: thread_ts, 3: topic,
                4: assumptions, 5: constraints, 6: risks,
                7: open_questions, 8: proposed_decisions,
                9: version, 10: created_at, 11: updated_at

        Returns:
            ReviewState model instance.
        """
        return ReviewState(
            id=str(row[0]),
            channel_id=row[1],
            thread_ts=row[2],
            topic=row[3],
            assumptions=[Assumption(**a) for a in (row[4] or [])],
            constraints=[Constraint(**c) for c in (row[5] or [])],
            risks=[Risk(**r) for r in (row[6] or [])],
            open_questions=[OpenQuestion(**q) for q in (row[7] or [])],
            proposed_decisions=[ProposedDecision(**d) for d in (row[8] or [])],
            version=row[9],
            created_at=row[10],
            updated_at=row[11],
        )
