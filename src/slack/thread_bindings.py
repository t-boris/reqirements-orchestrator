"""Thread to Jira ticket binding store.

Manages thread -> Jira ticket bindings for duplicate linking.

Phase 33-02: Database-backed persistence.
Legacy store: binds threads to Jira keys.
For entity-based bindings, see AnchorStore.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


@dataclass
class ThreadBinding:
    """A binding between a Slack thread and a Jira ticket."""

    channel_id: str
    thread_ts: str
    issue_key: str
    bound_at: datetime
    bound_by: str  # Slack user ID


class ThreadBindingStore:
    """Database-backed store for thread-to-Jira bindings.

    Persists bindings so context survives bot restarts.
    Legacy store: binds threads to Jira keys.
    For entity-based bindings, see AnchorStore.

    Usage:
        async with get_connection() as conn:
            store = ThreadBindingStore(conn)
            await store.create_tables()
            binding = await store.bind(channel_id, thread_ts, issue_key, bound_by)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create thread_bindings table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS thread_bindings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    issue_key TEXT NOT NULL,
                    bound_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    bound_by TEXT NOT NULL,

                    -- One binding per thread
                    UNIQUE(channel_id, thread_ts)
                )
            """)

            # Fast lookups by thread
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_thread_bindings_thread
                    ON thread_bindings(channel_id, thread_ts)
            """)

            # Fast lookups by issue
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_thread_bindings_issue
                    ON thread_bindings(issue_key)
            """)

            await self._conn.commit()

    async def bind(
        self,
        channel_id: str,
        thread_ts: str,
        issue_key: str,
        bound_by: str,
    ) -> ThreadBinding:
        """Bind a thread to a Jira ticket.

        Creates or updates the binding. Uses UPSERT to handle rebinding.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            issue_key: Jira issue key to link to
            bound_by: Slack user ID who created the binding

        Returns:
            Created or updated ThreadBinding
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO thread_bindings (channel_id, thread_ts, issue_key, bound_by, bound_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (channel_id, thread_ts)
                DO UPDATE SET issue_key = EXCLUDED.issue_key, bound_at = EXCLUDED.bound_at
                RETURNING channel_id, thread_ts, issue_key, bound_at, bound_by
                """,
                (channel_id, thread_ts, issue_key, bound_by, now),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        binding = ThreadBinding(
            channel_id=row[0],
            thread_ts=row[1],
            issue_key=row[2],
            bound_at=row[3],
            bound_by=row[4],
        )

        logger.info(
            "Thread bound to Jira ticket",
            extra={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "issue_key": issue_key,
                "bound_by": bound_by,
            },
        )

        return binding

    async def get_binding(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[ThreadBinding]:
        """Get binding for a thread if exists.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            ThreadBinding if exists, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT channel_id, thread_ts, issue_key, bound_at, bound_by
                FROM thread_bindings
                WHERE channel_id = %s AND thread_ts = %s
                """,
                (channel_id, thread_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return ThreadBinding(
            channel_id=row[0],
            thread_ts=row[1],
            issue_key=row[2],
            bound_at=row[3],
            bound_by=row[4],
        )

    async def unbind(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Remove binding for a thread.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            True if binding existed and was removed, False otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM thread_bindings
                WHERE channel_id = %s AND thread_ts = %s
                RETURNING id
                """,
                (channel_id, thread_ts),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if row:
            logger.info(
                "Thread unbound from Jira ticket",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                },
            )
            return True

        return False

    async def get_bindings_for_issue(
        self,
        issue_key: str,
    ) -> list[ThreadBinding]:
        """Get all thread bindings for a Jira issue.

        Args:
            issue_key: Jira issue key

        Returns:
            List of ThreadBinding objects for this issue
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT channel_id, thread_ts, issue_key, bound_at, bound_by
                FROM thread_bindings
                WHERE issue_key = %s
                ORDER BY bound_at DESC
                """,
                (issue_key,),
            )
            rows = await cur.fetchall()

        return [
            ThreadBinding(
                channel_id=row[0],
                thread_ts=row[1],
                issue_key=row[2],
                bound_at=row[3],
                bound_by=row[4],
            )
            for row in rows
        ]


# -------------------------------------------------------------------------
# Convenience functions - manage connection internally for simple operations
# -------------------------------------------------------------------------

async def bind_thread(
    channel_id: str,
    thread_ts: str,
    issue_key: str,
    bound_by: str,
) -> ThreadBinding:
    """Bind a thread to a Jira ticket (convenience wrapper).

    Manages database connection internally.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        issue_key: Jira issue key to link to
        bound_by: Slack user ID who created the binding

    Returns:
        Created or updated ThreadBinding
    """
    from src.db import get_connection

    async with get_connection() as conn:
        store = ThreadBindingStore(conn)
        return await store.bind(channel_id, thread_ts, issue_key, bound_by)


async def get_thread_binding(
    channel_id: str,
    thread_ts: str,
) -> Optional[ThreadBinding]:
    """Get binding for a thread (convenience wrapper).

    Manages database connection internally.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp

    Returns:
        ThreadBinding if exists, None otherwise
    """
    from src.db import get_connection

    async with get_connection() as conn:
        store = ThreadBindingStore(conn)
        return await store.get_binding(channel_id, thread_ts)


async def unbind_thread(
    channel_id: str,
    thread_ts: str,
) -> bool:
    """Remove binding for a thread (convenience wrapper).

    Manages database connection internally.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp

    Returns:
        True if binding existed and was removed, False otherwise
    """
    from src.db import get_connection

    async with get_connection() as conn:
        store = ThreadBindingStore(conn)
        return await store.unbind(channel_id, thread_ts)


# -------------------------------------------------------------------------
# Legacy singleton interface (DEPRECATED)
# -------------------------------------------------------------------------

class _LegacyBindingStoreAdapter:
    """Adapter to provide backward-compatible interface for get_binding_store().

    DEPRECATED: Use ThreadBindingStore with get_connection() directly,
    or use the convenience functions (bind_thread, get_thread_binding, unbind_thread).

    This adapter creates a new database connection for each operation.
    """

    async def bind(
        self,
        channel_id: str,
        thread_ts: str,
        issue_key: str,
        bound_by: str,
    ) -> ThreadBinding:
        """Bind a thread to a Jira ticket."""
        return await bind_thread(channel_id, thread_ts, issue_key, bound_by)

    async def get_binding(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[ThreadBinding]:
        """Get binding for a thread if exists."""
        return await get_thread_binding(channel_id, thread_ts)

    async def unbind(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Remove binding for a thread."""
        return await unbind_thread(channel_id, thread_ts)


# Global legacy singleton instance
_legacy_binding_store: Optional[_LegacyBindingStoreAdapter] = None


def get_binding_store() -> _LegacyBindingStoreAdapter:
    """Get the legacy ThreadBindingStore adapter.

    DEPRECATED: This returns an adapter that creates a new database
    connection for each operation. For better performance with multiple
    operations, use ThreadBindingStore with get_connection() directly.

    Returns:
        _LegacyBindingStoreAdapter instance
    """
    global _legacy_binding_store
    if _legacy_binding_store is None:
        _legacy_binding_store = _LegacyBindingStoreAdapter()
    return _legacy_binding_store
