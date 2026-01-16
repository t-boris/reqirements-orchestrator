"""Board state store for pinned Jira board messages.

Stores channel → board message mapping for update/removal tracking.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


@dataclass
class BoardState:
    """State of a pinned board in a channel."""

    channel_id: str
    message_ts: str
    created_at: datetime
    last_refresh_at: Optional[datetime] = None


class BoardStore:
    """Store for pinned board state per channel.

    Tracks which channels have a pinned board message for updates.

    Usage:
        async with get_connection() as conn:
            store = BoardStore(conn)
            await store.create_tables()
            await store.set_board(channel_id, message_ts)
            state = await store.get_board(channel_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create channel_board_state table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS channel_board_state (
                    channel_id TEXT PRIMARY KEY,
                    message_ts TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    last_refresh_at TIMESTAMPTZ
                )
            """)
            await self._conn.commit()

    async def get_board(self, channel_id: str) -> Optional[BoardState]:
        """Get board state for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            BoardState if board exists, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT channel_id, message_ts, created_at, last_refresh_at
                FROM channel_board_state
                WHERE channel_id = %s
                """,
                (channel_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return BoardState(
            channel_id=row[0],
            message_ts=row[1],
            created_at=row[2],
            last_refresh_at=row[3],
        )

    async def set_board(
        self,
        channel_id: str,
        message_ts: str,
    ) -> BoardState:
        """Set or update board state for a channel.

        Args:
            channel_id: Slack channel ID.
            message_ts: Timestamp of the board message.

        Returns:
            BoardState: The stored state.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO channel_board_state (
                    channel_id, message_ts, created_at, last_refresh_at
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (channel_id) DO UPDATE SET
                    message_ts = EXCLUDED.message_ts,
                    last_refresh_at = EXCLUDED.last_refresh_at
                RETURNING channel_id, message_ts, created_at, last_refresh_at
                """,
                (channel_id, message_ts, now, now),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return BoardState(
            channel_id=row[0],
            message_ts=row[1],
            created_at=row[2],
            last_refresh_at=row[3],
        )

    async def update_refresh_time(self, channel_id: str) -> bool:
        """Update last refresh time for a channel's board.

        Args:
            channel_id: Slack channel ID.

        Returns:
            True if board existed and was updated, False otherwise.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_board_state
                SET last_refresh_at = %s
                WHERE channel_id = %s
                RETURNING channel_id
                """,
                (now, channel_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    async def remove_board(self, channel_id: str) -> bool:
        """Remove board state for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            True if board existed and was removed, False otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM channel_board_state
                WHERE channel_id = %s
                RETURNING channel_id
                """,
                (channel_id,),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    async def has_board(self, channel_id: str) -> bool:
        """Check if a channel has a pinned board.

        Args:
            channel_id: Slack channel ID.

        Returns:
            True if board exists, False otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1 FROM channel_board_state
                WHERE channel_id = %s
                """,
                (channel_id,),
            )
            row = await cur.fetchone()

        return row is not None
