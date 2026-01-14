"""Session store with async CRUD operations using psycopg v3.

Provides database persistence for thread sessions and channel context.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from src.db.models import ChannelContext, ThreadSession


class SessionStore:
    """Async CRUD operations for session data using raw SQL.

    Usage:
        async with get_connection() as conn:
            store = SessionStore(conn)
            await store.create_tables()
            session = await store.get_or_create_session(channel_id, thread_ts, user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create tables if they don't exist.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            # Thread sessions table
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS thread_sessions (
                    id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'collecting',
                    jira_key TEXT,
                    epic_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(channel_id, thread_ts)
                )
            """)

            # Add epic_id column if it doesn't exist (for existing tables)
            await cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'thread_sessions' AND column_name = 'epic_id'
                    ) THEN
                        ALTER TABLE thread_sessions ADD COLUMN epic_id TEXT;
                    END IF;
                END $$;
            """)

            # Channel context table
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS channel_context (
                    id UUID PRIMARY KEY,
                    channel_id TEXT UNIQUE NOT NULL,
                    context_data JSONB DEFAULT '{}',
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            await self._conn.commit()

    async def get_or_create_session(
        self,
        channel_id: str,
        thread_ts: str,
        user_id: str,
    ) -> ThreadSession:
        """Get existing session or create a new one.

        Args:
            channel_id: Slack channel ID.
            thread_ts: Slack thread timestamp.
            user_id: Initiating user's Slack ID.

        Returns:
            ThreadSession: Existing or newly created session.
        """
        # Try to get existing session first
        existing = await self.get_session_by_thread(channel_id, thread_ts)
        if existing:
            return existing

        # Create new session
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO thread_sessions (id, channel_id, thread_ts, user_id, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, channel_id, thread_ts, user_id, status, jira_key, epic_id, created_at, updated_at
                """,
                (session_id, channel_id, thread_ts, user_id, "collecting", now, now),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return ThreadSession(
            id=str(row[0]),
            channel_id=row[1],
            thread_ts=row[2],
            user_id=row[3],
            status=row[4],
            jira_key=row[5],
            epic_id=row[6],
            created_at=row[7],
            updated_at=row[8],
        )

    async def update_session(
        self,
        session_id: str,
        status: str,
        jira_key: Optional[str] = None,
    ) -> ThreadSession:
        """Update session status and optionally set jira_key.

        Args:
            session_id: UUID of the session to update.
            status: New status (collecting, ready_to_sync, synced).
            jira_key: Optional Jira issue key to set.

        Returns:
            ThreadSession: Updated session.

        Raises:
            ValueError: If session not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            if jira_key is not None:
                await cur.execute(
                    """
                    UPDATE thread_sessions
                    SET status = %s, jira_key = %s, updated_at = %s
                    WHERE id = %s
                    RETURNING id, channel_id, thread_ts, user_id, status, jira_key, epic_id, created_at, updated_at
                    """,
                    (status, jira_key, now, session_id),
                )
            else:
                await cur.execute(
                    """
                    UPDATE thread_sessions
                    SET status = %s, updated_at = %s
                    WHERE id = %s
                    RETURNING id, channel_id, thread_ts, user_id, status, jira_key, epic_id, created_at, updated_at
                    """,
                    (status, now, session_id),
                )

            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Session not found: {session_id}")

        return ThreadSession(
            id=str(row[0]),
            channel_id=row[1],
            thread_ts=row[2],
            user_id=row[3],
            status=row[4],
            jira_key=row[5],
            epic_id=row[6],
            created_at=row[7],
            updated_at=row[8],
        )

    async def get_session_by_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[ThreadSession]:
        """Get session by channel and thread timestamp.

        Args:
            channel_id: Slack channel ID.
            thread_ts: Slack thread timestamp.

        Returns:
            ThreadSession if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, thread_ts, user_id, status, jira_key, epic_id, created_at, updated_at
                FROM thread_sessions
                WHERE channel_id = %s AND thread_ts = %s
                """,
                (channel_id, thread_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return ThreadSession(
            id=str(row[0]),
            channel_id=row[1],
            thread_ts=row[2],
            user_id=row[3],
            status=row[4],
            jira_key=row[5],
            epic_id=row[6],
            created_at=row[7],
            updated_at=row[8],
        )

    async def list_sessions_by_channel(self, channel_id: str) -> list[ThreadSession]:
        """List all sessions for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            List of ThreadSession objects for the channel.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, thread_ts, user_id, status, jira_key, epic_id, created_at, updated_at
                FROM thread_sessions
                WHERE channel_id = %s
                ORDER BY created_at DESC
                """,
                (channel_id,),
            )
            rows = await cur.fetchall()

        return [
            ThreadSession(
                id=str(row[0]),
                channel_id=row[1],
                thread_ts=row[2],
                user_id=row[3],
                status=row[4],
                jira_key=row[5],
                epic_id=row[6],
                created_at=row[7],
                updated_at=row[8],
            )
            for row in rows
        ]

    async def update_epic(
        self,
        channel_id: str,
        thread_ts: str,
        epic_id: str,
    ) -> ThreadSession:
        """Bind session to an Epic.

        Args:
            channel_id: Slack channel ID.
            thread_ts: Slack thread timestamp.
            epic_id: Jira Epic key to bind (e.g., PROJ-50).

        Returns:
            ThreadSession: Updated session.

        Raises:
            ValueError: If session not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE thread_sessions
                SET epic_id = %s, updated_at = %s
                WHERE channel_id = %s AND thread_ts = %s
                RETURNING id, channel_id, thread_ts, user_id, status, jira_key, epic_id, created_at, updated_at
                """,
                (epic_id, now, channel_id, thread_ts),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Session not found: {channel_id}/{thread_ts}")

        return ThreadSession(
            id=str(row[0]),
            channel_id=row[1],
            thread_ts=row[2],
            user_id=row[3],
            status=row[4],
            jira_key=row[5],
            epic_id=row[6],
            created_at=row[7],
            updated_at=row[8],
        )

    async def get_or_create(
        self,
        channel_id: str,
        thread_ts: str,
        user_id: str = "unknown",
    ) -> ThreadSession:
        """Alias for get_or_create_session with optional user_id.

        Convenience method used by binding flow where user_id may not be available.
        """
        return await self.get_or_create_session(channel_id, thread_ts, user_id)
