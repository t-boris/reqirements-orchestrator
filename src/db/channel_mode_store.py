"""Channel mode store with async CRUD operations.

Provides database persistence for channel mode configuration.
"""
import uuid
from datetime import datetime, timezone

from psycopg import AsyncConnection

from src.db.models import ChannelMode, ChannelModeConfig


class ChannelModeStore:
    """Async CRUD operations for channel mode configuration.

    Usage:
        async with get_connection() as conn:
            store = ChannelModeStore(conn)
            config = await store.get_or_create(channel_id, user_id)
            await store.set_mode(channel_id, ChannelMode.PROJECT, user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create channel_mode table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS channel_mode (
                    id UUID PRIMARY KEY,
                    channel_id TEXT UNIQUE NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'project',
                    primary_epic TEXT,
                    set_by TEXT NOT NULL,
                    set_at TIMESTAMPTZ NOT NULL,
                    suggestion_shown BOOLEAN DEFAULT FALSE,
                    suggestion_accepted BOOLEAN,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await self._conn.commit()

    async def get(self, channel_id: str) -> ChannelModeConfig | None:
        """Get mode config for a channel."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, mode, primary_epic, set_by, set_at,
                       suggestion_shown, suggestion_accepted, created_at, updated_at
                FROM channel_mode
                WHERE channel_id = %s
                """,
                (channel_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return ChannelModeConfig(
            id=str(row[0]),
            channel_id=row[1],
            mode=ChannelMode(row[2]),
            primary_epic=row[3],
            set_by=row[4],
            set_at=row[5],
            suggestion_shown=row[6],
            suggestion_accepted=row[7],
            created_at=row[8],
            updated_at=row[9],
        )

    async def get_or_create(
        self,
        channel_id: str,
        default_user: str,
    ) -> ChannelModeConfig:
        """Get existing config or create with default PROJECT mode."""
        existing = await self.get(channel_id)
        if existing:
            return existing

        config_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO channel_mode (id, channel_id, mode, set_by, set_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, channel_id, mode, primary_epic, set_by, set_at,
                          suggestion_shown, suggestion_accepted, created_at, updated_at
                """,
                (config_id, channel_id, ChannelMode.PROJECT.value, default_user, now, now, now),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return ChannelModeConfig(
            id=str(row[0]),
            channel_id=row[1],
            mode=ChannelMode(row[2]),
            primary_epic=row[3],
            set_by=row[4],
            set_at=row[5],
            suggestion_shown=row[6],
            suggestion_accepted=row[7],
            created_at=row[8],
            updated_at=row[9],
        )

    async def set_mode(
        self,
        channel_id: str,
        mode: ChannelMode,
        user_id: str,
        *,
        primary_epic: str | None = None,
    ) -> ChannelModeConfig:
        """Set mode for a channel. Creates config if not exists."""
        now = datetime.now(timezone.utc)
        config_id = str(uuid.uuid4())

        async with self._conn.cursor() as cur:
            # Upsert pattern
            await cur.execute(
                """
                INSERT INTO channel_mode (id, channel_id, mode, primary_epic, set_by, set_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (channel_id) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    primary_epic = EXCLUDED.primary_epic,
                    set_by = EXCLUDED.set_by,
                    set_at = EXCLUDED.set_at,
                    updated_at = EXCLUDED.updated_at
                RETURNING id, channel_id, mode, primary_epic, set_by, set_at,
                          suggestion_shown, suggestion_accepted, created_at, updated_at
                """,
                (config_id, channel_id, mode.value, primary_epic, user_id, now, now, now),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return ChannelModeConfig(
            id=str(row[0]),
            channel_id=row[1],
            mode=ChannelMode(row[2]),
            primary_epic=row[3],
            set_by=row[4],
            set_at=row[5],
            suggestion_shown=row[6],
            suggestion_accepted=row[7],
            created_at=row[8],
            updated_at=row[9],
        )

    async def mark_suggestion_shown(self, channel_id: str) -> bool:
        """Mark that mode suggestion has been shown. Returns True if updated."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_mode
                SET suggestion_shown = TRUE, updated_at = NOW()
                WHERE channel_id = %s
                RETURNING id
                """,
                (channel_id,),
            )
            row = await cur.fetchone()
            await self._conn.commit()
        return row is not None

    async def set_suggestion_response(
        self,
        channel_id: str,
        accepted: bool,
    ) -> bool:
        """Record user's response to mode suggestion. Returns True if updated."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_mode
                SET suggestion_accepted = %s, updated_at = NOW()
                WHERE channel_id = %s
                RETURNING id
                """,
                (accepted, channel_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()
        return row is not None
