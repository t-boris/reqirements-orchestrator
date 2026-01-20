"""Commit store with async CRUD operations.

Provides database persistence for channel commit log entries.
"""
import uuid
from datetime import datetime, timezone

from psycopg import AsyncConnection

from src.db.models import CommitType, CommitEntry


class CommitStore:
    """Async CRUD operations for commit log entries.

    Usage:
        async with get_connection() as conn:
            store = CommitStore(conn)
            entry = await store.create(channel_id, CommitType.DECISION, "Use worker", user_id)
            recent = await store.list_recent(channel_id, limit=10)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create commit_log table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS commit_log (
                    id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    commit_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    workitem_id UUID,
                    thread_ts TEXT,
                    committed_by TEXT NOT NULL,
                    committed_at TIMESTAMPTZ NOT NULL
                )
            """)

            # Index for efficient channel queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_commit_log_channel
                ON commit_log(channel_id, committed_at DESC)
            """)

            await self._conn.commit()

    async def create(
        self,
        channel_id: str,
        commit_type: CommitType,
        summary: str,
        user_id: str,
        *,
        workitem_id: str | None = None,
        thread_ts: str | None = None,
    ) -> CommitEntry:
        """Create a new commit entry."""
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO commit_log (id, channel_id, commit_type, summary, workitem_id, thread_ts, committed_by, committed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, channel_id, commit_type, summary, workitem_id, thread_ts, committed_by, committed_at
                """,
                (entry_id, channel_id, commit_type.value, summary, workitem_id, thread_ts, user_id, now)
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return CommitEntry(
            id=str(row[0]),
            channel_id=row[1],
            commit_type=CommitType(row[2]),
            summary=row[3],
            workitem_id=str(row[4]) if row[4] else None,
            thread_ts=row[5],
            committed_by=row[6],
            committed_at=row[7],
        )

    async def get(self, entry_id: str) -> CommitEntry | None:
        """Get a commit entry by ID."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, commit_type, summary, workitem_id, thread_ts, committed_by, committed_at
                FROM commit_log
                WHERE id = %s
                """,
                (entry_id,)
            )
            row = await cur.fetchone()

        if not row:
            return None

        return CommitEntry(
            id=str(row[0]),
            channel_id=row[1],
            commit_type=CommitType(row[2]),
            summary=row[3],
            workitem_id=str(row[4]) if row[4] else None,
            thread_ts=row[5],
            committed_by=row[6],
            committed_at=row[7],
        )

    async def list_recent(
        self,
        channel_id: str,
        *,
        limit: int = 10,
    ) -> list[CommitEntry]:
        """List recent commits for a channel, newest first."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, commit_type, summary, workitem_id, thread_ts, committed_by, committed_at
                FROM commit_log
                WHERE channel_id = %s
                ORDER BY committed_at DESC
                LIMIT %s
                """,
                (channel_id, limit)
            )
            rows = await cur.fetchall()

        return [
            CommitEntry(
                id=str(row[0]),
                channel_id=row[1],
                commit_type=CommitType(row[2]),
                summary=row[3],
                workitem_id=str(row[4]) if row[4] else None,
                thread_ts=row[5],
                committed_by=row[6],
                committed_at=row[7],
            )
            for row in rows
        ]

    async def count_by_channel(self, channel_id: str) -> int:
        """Count commits for a channel."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM commit_log WHERE channel_id = %s",
                (channel_id,)
            )
            row = await cur.fetchone()
        return row[0] if row else 0
