"""Thread state persistence.

Stores thread-level state (the working tree in Git model).
"""

from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.graph.state import Phase, ThreadState


class ThreadStateStore:
    """CRUD operations for thread state."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create thread_states table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS thread_states (
                    thread_ts TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    draft JSONB,
                    draft_type TEXT,
                    pending_questions JSONB DEFAULT '[]',
                    step_count INTEGER DEFAULT 0,
                    phase TEXT DEFAULT 'collecting',
                    reask_count INTEGER DEFAULT 0,
                    workflow_step TEXT,
                    last_action TEXT,
                    last_intent TEXT,
                    last_decision JSONB,
                    bound_workitem_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (channel_id, thread_ts)
                )
            """)

            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_thread_states_channel
                ON thread_states(channel_id)
            """)

            await self._conn.commit()

    async def get(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[ThreadState]:
        """Get thread state."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM thread_states
                WHERE channel_id = %s AND thread_ts = %s
                """,
                (channel_id, thread_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return ThreadState(
            thread_ts=row[0],
            channel_id=row[1],
            draft=row[2],
            draft_type=row[3],
            pending_questions=row[4] or [],
            step_count=row[5],
            phase=Phase(row[6]),
            reask_count=row[7],
            workflow_step=row[8],
            last_action=row[9],
            last_intent=row[10],
            last_decision=row[11],
            bound_workitem_id=row[12],
        )

    async def get_or_create(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> ThreadState:
        """Get thread state, creating if not exists."""
        state = await self.get(channel_id, thread_ts)
        if state:
            return state

        # Create new
        state = ThreadState(thread_ts=thread_ts, channel_id=channel_id)
        await self.save(state)
        return state

    async def save(self, state: ThreadState) -> ThreadState:
        """Save thread state (upsert)."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO thread_states
                (thread_ts, channel_id, draft, draft_type, pending_questions,
                 step_count, phase, reask_count, workflow_step, last_action,
                 last_intent, last_decision, bound_workitem_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (channel_id, thread_ts) DO UPDATE SET
                    draft = EXCLUDED.draft,
                    draft_type = EXCLUDED.draft_type,
                    pending_questions = EXCLUDED.pending_questions,
                    step_count = EXCLUDED.step_count,
                    phase = EXCLUDED.phase,
                    reask_count = EXCLUDED.reask_count,
                    workflow_step = EXCLUDED.workflow_step,
                    last_action = EXCLUDED.last_action,
                    last_intent = EXCLUDED.last_intent,
                    last_decision = EXCLUDED.last_decision,
                    bound_workitem_id = EXCLUDED.bound_workitem_id,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    state.thread_ts,
                    state.channel_id,
                    state.draft,
                    state.draft_type,
                    state.pending_questions,
                    state.step_count,
                    state.phase.value,
                    state.reask_count,
                    state.workflow_step,
                    state.last_action,
                    state.last_intent,
                    state.last_decision,
                    state.bound_workitem_id,
                    now,
                ),
            )
            await self._conn.commit()

        return state

    async def get_active_threads(self, channel_id: str) -> list[ThreadState]:
        """Get all active threads for a channel."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM thread_states
                WHERE channel_id = %s
                AND phase NOT IN ('approved', 'rejected')
                ORDER BY updated_at DESC
                """,
                (channel_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_state(row) for row in rows]

    def _row_to_state(self, row) -> ThreadState:
        """Convert row to ThreadState."""
        return ThreadState(
            thread_ts=row[0],
            channel_id=row[1],
            draft=row[2],
            draft_type=row[3],
            pending_questions=row[4] or [],
            step_count=row[5],
            phase=Phase(row[6]),
            reask_count=row[7],
            workflow_step=row[8],
            last_action=row[9],
            last_intent=row[10],
            last_decision=row[11],
            bound_workitem_id=row[12],
        )
