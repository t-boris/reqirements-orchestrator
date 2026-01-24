"""ConversationModeStore for persisting conversation mode state.

Follows ThreadStateStore pattern for CRUD operations on conversation_modes table.
"""

from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.schemas.conversation_mode import (
    ConversationMode,
    ConversationModeState,
    ModeTransitionReason,
)


class ConversationModeStore:
    """CRUD operations for conversation mode state."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create conversation_modes table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS conversation_modes (
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'passive',
                    entered_at TIMESTAMPTZ NOT NULL,
                    last_activity TIMESTAMPTZ NOT NULL,
                    unanswered_questions INTEGER NOT NULL DEFAULT 0,
                    transition_reason TEXT,
                    PRIMARY KEY (channel_id, thread_ts)
                )
            """)

            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversation_modes_channel
                ON conversation_modes(channel_id)
            """)

            await self._conn.commit()

    async def get(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[ConversationModeState]:
        """Get current mode state for thread.

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp

        Returns:
            ConversationModeState if exists, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT channel_id, thread_ts, mode, entered_at, last_activity,
                       unanswered_questions, transition_reason
                FROM conversation_modes
                WHERE channel_id = %s AND thread_ts = %s
                """,
                (channel_id, thread_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_state(row)

    async def get_or_create(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> ConversationModeState:
        """Get or create mode state (defaults to PASSIVE).

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp

        Returns:
            Existing or newly created ConversationModeState
        """
        state = await self.get(channel_id, thread_ts)
        if state:
            return state

        # Create new state with PASSIVE mode
        now = datetime.now(timezone.utc)
        state = ConversationModeState(
            channel_id=channel_id,
            thread_ts=thread_ts,
            mode=ConversationMode.PASSIVE,
            entered_at=now,
            last_activity=now,
            unanswered_questions=0,
            transition_reason=None,
        )

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO conversation_modes
                (channel_id, thread_ts, mode, entered_at, last_activity,
                 unanswered_questions, transition_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (channel_id, thread_ts) DO NOTHING
                """,
                (
                    state.channel_id,
                    state.thread_ts,
                    state.mode.value,
                    state.entered_at,
                    state.last_activity,
                    state.unanswered_questions,
                    None,
                ),
            )
            await self._conn.commit()

        return state

    async def transition(
        self,
        channel_id: str,
        thread_ts: str,
        new_mode: ConversationMode,
        reason: ModeTransitionReason,
    ) -> ConversationModeState:
        """Transition to new mode with reason.

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp
            new_mode: Target conversation mode
            reason: Why the transition is happening

        Returns:
            Updated ConversationModeState
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO conversation_modes
                (channel_id, thread_ts, mode, entered_at, last_activity,
                 unanswered_questions, transition_reason)
                VALUES (%s, %s, %s, %s, %s, 0, %s)
                ON CONFLICT (channel_id, thread_ts) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    entered_at = EXCLUDED.entered_at,
                    last_activity = EXCLUDED.last_activity,
                    unanswered_questions = 0,
                    transition_reason = EXCLUDED.transition_reason
                RETURNING channel_id, thread_ts, mode, entered_at, last_activity,
                          unanswered_questions, transition_reason
                """,
                (
                    channel_id,
                    thread_ts,
                    new_mode.value,
                    now,
                    now,
                    reason.value,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_state(row)

    async def increment_unanswered(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> int:
        """Increment unanswered question count, return new value.

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp

        Returns:
            New unanswered question count
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE conversation_modes
                SET unanswered_questions = unanswered_questions + 1,
                    last_activity = %s
                WHERE channel_id = %s AND thread_ts = %s
                RETURNING unanswered_questions
                """,
                (datetime.now(timezone.utc), channel_id, thread_ts),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if row:
            return row[0]
        return 0

    async def reset_unanswered(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> None:
        """Reset unanswered count to 0 (on new user message).

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE conversation_modes
                SET unanswered_questions = 0,
                    last_activity = %s
                WHERE channel_id = %s AND thread_ts = %s
                """,
                (datetime.now(timezone.utc), channel_id, thread_ts),
            )
            await self._conn.commit()

    async def update_activity(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> None:
        """Update last_activity timestamp.

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE conversation_modes
                SET last_activity = %s
                WHERE channel_id = %s AND thread_ts = %s
                """,
                (datetime.now(timezone.utc), channel_id, thread_ts),
            )
            await self._conn.commit()

    def _row_to_state(self, row) -> ConversationModeState:
        """Convert database row to ConversationModeState.

        Args:
            row: Database row tuple

        Returns:
            ConversationModeState instance
        """
        transition_reason = None
        if row[6]:
            transition_reason = ModeTransitionReason(row[6])

        return ConversationModeState(
            channel_id=row[0],
            thread_ts=row[1],
            mode=ConversationMode(row[2]),
            entered_at=row[3],
            last_activity=row[4],
            unanswered_questions=row[5],
            transition_reason=transition_reason,
        )
