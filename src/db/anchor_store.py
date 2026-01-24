"""AnchorStore with async CRUD operations using psycopg v3.

Store for anchor message tracking. Provides bidirectional lookups:
- (anchor_type, object_id) -> anchor message
- (channel_id, message_ts) -> (anchor_type, object_id)

An anchor message is the canonical Slack representation of an object.
Every object (Decision, WorkItem, ChangeRequest, Draft) has at most one anchor
message per channel.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from psycopg import AsyncConnection

from src.schemas.anchor import AnchorMessage, AnchorType


class AnchorStore:
    """Store for anchor message tracking.

    Provides bidirectional lookups:
    - (anchor_type, object_id) -> anchor message
    - (channel_id, message_ts) -> (anchor_type, object_id)

    Usage:
        async with get_connection() as conn:
            store = AnchorStore(conn)
            anchor = await store.create_anchor(
                AnchorType.DECISION,
                "DEC-41",
                channel_id,
                message_ts,
                user_id,
            )
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create anchor_messages table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS anchor_messages (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    anchor_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    message_ts TEXT NOT NULL,
                    thread_ts TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    created_by TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,

                    -- Each object has one anchor per channel
                    UNIQUE(anchor_type, object_id, channel_id)
                )
            """)

            # Fast lookups by message (for thread resolution)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchor_messages_message
                ON anchor_messages(channel_id, message_ts)
            """)

            # Fast lookups by object (for updates)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_anchor_messages_object
                ON anchor_messages(anchor_type, object_id)
            """)

            await self._conn.commit()

    async def create_anchor(
        self,
        anchor_type: AnchorType,
        object_id: str,
        channel_id: str,
        message_ts: str,
        created_by: str,
        thread_ts: Optional[str] = None,
    ) -> AnchorMessage:
        """Create a new anchor message record.

        Args:
            anchor_type: Type of entity (decision, workitem, etc.).
            object_id: Entity ID (decision_id, workitem_id, etc.).
            channel_id: Slack channel where anchor exists.
            message_ts: The anchor message timestamp in Slack.
            created_by: User who triggered anchor creation.
            thread_ts: Thread for discussion (usually same as message_ts).

        Returns:
            AnchorMessage: Newly created anchor record.

        Raises:
            Exception: If anchor already exists for (anchor_type, object_id, channel_id).
        """
        anchor_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        # Default thread_ts to message_ts (thread starts from anchor)
        effective_thread_ts = thread_ts if thread_ts is not None else message_ts

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO anchor_messages (
                    id, anchor_type, object_id, channel_id, message_ts,
                    thread_ts, created_at, updated_at, created_by, version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, anchor_type, object_id, channel_id, message_ts,
                          thread_ts, created_at, updated_at, created_by, version
                """,
                (
                    str(anchor_id),
                    anchor_type.value,
                    object_id,
                    channel_id,
                    message_ts,
                    effective_thread_ts,
                    now,
                    now,
                    created_by,
                    1,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_anchor(row)

    async def get_by_message(
        self,
        channel_id: str,
        message_ts: str,
    ) -> Optional[AnchorMessage]:
        """Lookup anchor by Slack message coordinates.

        Use case: When user posts in thread, find what object the thread is for.

        Args:
            channel_id: Slack channel ID.
            message_ts: Message timestamp (parent message ts for thread).

        Returns:
            AnchorMessage if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, anchor_type, object_id, channel_id, message_ts,
                       thread_ts, created_at, updated_at, created_by, version
                FROM anchor_messages
                WHERE channel_id = %s AND message_ts = %s
                """,
                (channel_id, message_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_anchor(row)

    async def get_by_object(
        self,
        anchor_type: AnchorType,
        object_id: str,
        channel_id: Optional[str] = None,
    ) -> Optional[AnchorMessage]:
        """Lookup anchor by object identity.

        Use case: When updating object, find its anchor to update.
        If channel_id provided, scope to that channel.

        Args:
            anchor_type: Type of entity (decision, workitem, etc.).
            object_id: Entity ID (decision_id, workitem_id, etc.).
            channel_id: Optional channel scope.

        Returns:
            AnchorMessage if found, None otherwise.
        """
        if channel_id is not None:
            query = """
                SELECT id, anchor_type, object_id, channel_id, message_ts,
                       thread_ts, created_at, updated_at, created_by, version
                FROM anchor_messages
                WHERE anchor_type = %s AND object_id = %s AND channel_id = %s
            """
            params = (anchor_type.value, object_id, channel_id)
        else:
            query = """
                SELECT id, anchor_type, object_id, channel_id, message_ts,
                       thread_ts, created_at, updated_at, created_by, version
                FROM anchor_messages
                WHERE anchor_type = %s AND object_id = %s
                LIMIT 1
            """
            params = (anchor_type.value, object_id)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_anchor(row)

    async def get(self, anchor_id: UUID) -> Optional[AnchorMessage]:
        """Get anchor by ID.

        Args:
            anchor_id: UUID of the anchor.

        Returns:
            AnchorMessage if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, anchor_type, object_id, channel_id, message_ts,
                       thread_ts, created_at, updated_at, created_by, version
                FROM anchor_messages
                WHERE id = %s
                """,
                (str(anchor_id),),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_anchor(row)

    async def update_anchor(
        self,
        anchor_id: UUID,
        expected_version: int,
    ) -> bool:
        """Update anchor with optimistic locking.

        Returns False if version mismatch (concurrent update).
        Increments version number on success.

        Args:
            anchor_id: UUID of the anchor to update.
            expected_version: Expected current version (for optimistic locking).

        Returns:
            True if updated successfully, False if version mismatch or not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE anchor_messages
                SET version = version + 1,
                    updated_at = %s
                WHERE id = %s AND version = %s
                RETURNING id
                """,
                (now, str(anchor_id), expected_version),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    async def delete_anchor(
        self,
        anchor_id: UUID,
    ) -> bool:
        """Delete anchor (when object deleted or message removed).

        Args:
            anchor_id: UUID of the anchor to delete.

        Returns:
            True if deleted, False if not found.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM anchor_messages
                WHERE id = %s
                RETURNING id
                """,
                (str(anchor_id),),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    async def list_by_channel(
        self,
        channel_id: str,
        anchor_type: Optional[AnchorType] = None,
        limit: int = 50,
    ) -> list[AnchorMessage]:
        """List anchor messages in a channel.

        Args:
            channel_id: Slack channel ID.
            anchor_type: Optional filter by anchor type.
            limit: Maximum anchors to return.

        Returns:
            List of AnchorMessage objects, ordered by created_at DESC.
        """
        if anchor_type is not None:
            query = """
                SELECT id, anchor_type, object_id, channel_id, message_ts,
                       thread_ts, created_at, updated_at, created_by, version
                FROM anchor_messages
                WHERE channel_id = %s AND anchor_type = %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            params = (channel_id, anchor_type.value, limit)
        else:
            query = """
                SELECT id, anchor_type, object_id, channel_id, message_ts,
                       thread_ts, created_at, updated_at, created_by, version
                FROM anchor_messages
                WHERE channel_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            params = (channel_id, limit)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_anchor(row) for row in rows]

    def _row_to_anchor(self, row: tuple) -> AnchorMessage:
        """Convert database row to AnchorMessage model.

        Args:
            row: Tuple from database query.
                Expected order (10 columns):
                0: id, 1: anchor_type, 2: object_id, 3: channel_id,
                4: message_ts, 5: thread_ts, 6: created_at, 7: updated_at,
                8: created_by, 9: version

        Returns:
            AnchorMessage model instance.
        """
        return AnchorMessage(
            id=UUID(str(row[0])),
            anchor_type=AnchorType(row[1]),
            object_id=row[2],
            channel_id=row[3],
            message_ts=row[4],
            thread_ts=row[5],
            created_at=row[6],
            updated_at=row[7],
            created_by=row[8],
            version=row[9],
        )
