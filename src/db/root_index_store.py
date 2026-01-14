"""Root message index store for channel activity tracking."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.config.settings import get_settings
from src.db.models import RootIndex


class RootIndexStore:
    """Async CRUD for root message index.

    Usage:
        async with get_connection() as conn:
            store = RootIndexStore(conn)
            await store.index_root(team_id, channel_id, root_ts, text_summary)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create root_index table."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS root_index (
                    id UUID PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    root_ts TEXT NOT NULL,
                    text_summary TEXT,
                    entities JSONB DEFAULT '[]',
                    epic_id TEXT,
                    ticket_keys JSONB DEFAULT '[]',
                    is_pinned BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(team_id, channel_id, root_ts)
                )
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_root_channel
                ON root_index(team_id, channel_id, created_at DESC)
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_root_epic
                ON root_index(team_id, epic_id)
                WHERE epic_id IS NOT NULL
            """)
            await self._conn.commit()

    async def index_root(
        self,
        team_id: str,
        channel_id: str,
        root_ts: str,
        text_summary: Optional[str] = None,
        entities: Optional[list[str]] = None,
    ) -> RootIndex:
        """Add or update root index entry."""
        now = datetime.now(timezone.utc)
        root_id = str(uuid.uuid4())
        entities_list = entities or []

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO root_index (id, team_id, channel_id, root_ts, text_summary, entities, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (team_id, channel_id, root_ts) DO UPDATE
                SET text_summary = COALESCE(EXCLUDED.text_summary, root_index.text_summary),
                    entities = CASE
                        WHEN EXCLUDED.entities != '[]'::jsonb THEN EXCLUDED.entities
                        ELSE root_index.entities
                    END,
                    updated_at = EXCLUDED.updated_at
                RETURNING id, team_id, channel_id, root_ts, text_summary, entities, epic_id, ticket_keys, is_pinned, created_at, updated_at
                """,
                (root_id, team_id, channel_id, root_ts, text_summary, json.dumps(entities_list), now, now),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return RootIndex(
            id=str(row[0]),
            team_id=row[1],
            channel_id=row[2],
            root_ts=row[3],
            text_summary=row[4],
            entities=row[5] if row[5] else [],
            epic_id=row[6],
            ticket_keys=row[7] if row[7] else [],
            is_pinned=row[8],
            created_at=row[9],
            updated_at=row[10],
        )

    async def link_epic(
        self, team_id: str, channel_id: str, root_ts: str, epic_id: str
    ) -> RootIndex:
        """Link root to an epic."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE root_index
                SET epic_id = %s, updated_at = %s
                WHERE team_id = %s AND channel_id = %s AND root_ts = %s
                RETURNING id, team_id, channel_id, root_ts, text_summary, entities, epic_id, ticket_keys, is_pinned, created_at, updated_at
                """,
                (epic_id, now, team_id, channel_id, root_ts),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Root index not found: {team_id}/{channel_id}/{root_ts}")

        return RootIndex(
            id=str(row[0]),
            team_id=row[1],
            channel_id=row[2],
            root_ts=row[3],
            text_summary=row[4],
            entities=row[5] if row[5] else [],
            epic_id=row[6],
            ticket_keys=row[7] if row[7] else [],
            is_pinned=row[8],
            created_at=row[9],
            updated_at=row[10],
        )

    async def add_ticket(
        self, team_id: str, channel_id: str, root_ts: str, ticket_key: str
    ) -> RootIndex:
        """Add ticket key to root's ticket_keys array."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE root_index
                SET ticket_keys = ticket_keys || %s::jsonb,
                    updated_at = %s
                WHERE team_id = %s AND channel_id = %s AND root_ts = %s
                  AND NOT ticket_keys ? %s
                RETURNING id, team_id, channel_id, root_ts, text_summary, entities, epic_id, ticket_keys, is_pinned, created_at, updated_at
                """,
                (json.dumps([ticket_key]), now, team_id, channel_id, root_ts, ticket_key),
            )
            row = await cur.fetchone()

            # If no row returned, ticket already exists or root not found
            if not row:
                await cur.execute(
                    """
                    SELECT id, team_id, channel_id, root_ts, text_summary, entities, epic_id, ticket_keys, is_pinned, created_at, updated_at
                    FROM root_index
                    WHERE team_id = %s AND channel_id = %s AND root_ts = %s
                    """,
                    (team_id, channel_id, root_ts),
                )
                row = await cur.fetchone()
                if not row:
                    raise ValueError(f"Root index not found: {team_id}/{channel_id}/{root_ts}")
            else:
                await self._conn.commit()

        return RootIndex(
            id=str(row[0]),
            team_id=row[1],
            channel_id=row[2],
            root_ts=row[3],
            text_summary=row[4],
            entities=row[5] if row[5] else [],
            epic_id=row[6],
            ticket_keys=row[7] if row[7] else [],
            is_pinned=row[8],
            created_at=row[9],
            updated_at=row[10],
        )

    async def mark_pinned(
        self, team_id: str, channel_id: str, root_ts: str, is_pinned: bool
    ) -> None:
        """Mark root as pinned (lives beyond retention)."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE root_index
                SET is_pinned = %s, updated_at = %s
                WHERE team_id = %s AND channel_id = %s AND root_ts = %s
                """,
                (is_pinned, now, team_id, channel_id, root_ts),
            )
            await self._conn.commit()

    async def get_recent_roots(
        self,
        team_id: str,
        channel_id: str,
        window_days: Optional[int] = None,
        limit: int = 50,
    ) -> list[RootIndex]:
        """Get recent roots within retention window.

        Includes:
        - All roots within window_days
        - All pinned roots regardless of age
        """
        settings = get_settings()
        window = window_days or settings.channel_context_root_window_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=window)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, team_id, channel_id, root_ts, text_summary, entities, epic_id, ticket_keys, is_pinned, created_at, updated_at
                FROM root_index
                WHERE team_id = %s AND channel_id = %s
                  AND (created_at >= %s OR is_pinned = TRUE)
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (team_id, channel_id, cutoff, limit),
            )
            rows = await cur.fetchall()

        return [
            RootIndex(
                id=str(row[0]),
                team_id=row[1],
                channel_id=row[2],
                root_ts=row[3],
                text_summary=row[4],
                entities=row[5] if row[5] else [],
                epic_id=row[6],
                ticket_keys=row[7] if row[7] else [],
                is_pinned=row[8],
                created_at=row[9],
                updated_at=row[10],
            )
            for row in rows
        ]

    async def get_roots_by_epic(self, team_id: str, epic_id: str) -> list[RootIndex]:
        """Get all roots linked to an epic."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, team_id, channel_id, root_ts, text_summary, entities, epic_id, ticket_keys, is_pinned, created_at, updated_at
                FROM root_index
                WHERE team_id = %s AND epic_id = %s
                ORDER BY created_at DESC
                """,
                (team_id, epic_id),
            )
            rows = await cur.fetchall()

        return [
            RootIndex(
                id=str(row[0]),
                team_id=row[1],
                channel_id=row[2],
                root_ts=row[3],
                text_summary=row[4],
                entities=row[5] if row[5] else [],
                epic_id=row[6],
                ticket_keys=row[7] if row[7] else [],
                is_pinned=row[8],
                created_at=row[9],
                updated_at=row[10],
            )
            for row in rows
        ]

    async def cleanup_old_roots(
        self, team_id: str, channel_id: str, window_days: int
    ) -> int:
        """Delete non-pinned roots older than window. Return count deleted."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM root_index
                WHERE team_id = %s AND channel_id = %s
                  AND created_at < %s
                  AND is_pinned = FALSE
                """,
                (team_id, channel_id, cutoff),
            )
            deleted = cur.rowcount
            await self._conn.commit()

        return deleted
