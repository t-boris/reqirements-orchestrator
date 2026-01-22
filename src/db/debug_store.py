"""Debug mode store with async CRUD operations.

Provides database persistence for per-channel debug mode configuration.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.db.models import DebugModeConfig


class DebugStore:
    """Async CRUD operations for debug mode configuration.

    Usage:
        async with get_connection() as conn:
            store = DebugStore(conn)
            await store.create_tables()
            if await store.is_enabled(channel_id):
                # Output debug info
                pass
            await store.enable(channel_id, user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create debug_mode table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS debug_mode (
                    id UUID PRIMARY KEY,
                    channel_id TEXT UNIQUE NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    verbosity TEXT NOT NULL DEFAULT 'full',
                    set_by TEXT NOT NULL,
                    set_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await self._conn.commit()

    async def get(self, channel_id: str) -> Optional[DebugModeConfig]:
        """Get debug mode config for a channel."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, enabled, verbosity, set_by, set_at,
                       created_at, updated_at
                FROM debug_mode
                WHERE channel_id = %s
                """,
                (channel_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return DebugModeConfig(
            id=str(row[0]),
            channel_id=row[1],
            enabled=row[2],
            verbosity=row[3],
            set_by=row[4],
            set_at=row[5],
            created_at=row[6],
            updated_at=row[7],
        )

    async def is_enabled(self, channel_id: str) -> bool:
        """Check if debug mode is enabled for a channel."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT enabled FROM debug_mode WHERE channel_id = %s
                """,
                (channel_id,),
            )
            row = await cur.fetchone()

        return row[0] if row else False

    async def enable(
        self,
        channel_id: str,
        user_id: str,
        verbosity: str = "full",
    ) -> DebugModeConfig:
        """Enable debug mode for a channel."""
        return await self._set(channel_id, enabled=True, user_id=user_id, verbosity=verbosity)

    async def disable(
        self,
        channel_id: str,
        user_id: str,
    ) -> DebugModeConfig:
        """Disable debug mode for a channel."""
        config = await self.get(channel_id)
        verbosity = config.verbosity if config else "full"
        return await self._set(channel_id, enabled=False, user_id=user_id, verbosity=verbosity)

    async def _set(
        self,
        channel_id: str,
        enabled: bool,
        user_id: str,
        verbosity: str,
    ) -> DebugModeConfig:
        """Internal upsert for debug mode configuration."""
        config_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO debug_mode (id, channel_id, enabled, verbosity, set_by, set_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (channel_id) DO UPDATE SET
                    enabled = EXCLUDED.enabled,
                    verbosity = EXCLUDED.verbosity,
                    set_by = EXCLUDED.set_by,
                    set_at = EXCLUDED.set_at,
                    updated_at = EXCLUDED.updated_at
                RETURNING id, channel_id, enabled, verbosity, set_by, set_at, created_at, updated_at
                """,
                (config_id, channel_id, enabled, verbosity, user_id, now, now, now),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return DebugModeConfig(
            id=str(row[0]),
            channel_id=row[1],
            enabled=row[2],
            verbosity=row[3],
            set_by=row[4],
            set_at=row[5],
            created_at=row[6],
            updated_at=row[7],
        )
