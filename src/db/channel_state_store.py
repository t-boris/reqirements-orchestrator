"""Channel state persistence.

Stores channel-level state (the repository in Git model).
"""

from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.graph.state import ChannelState


class ChannelStateStore:
    """CRUD operations for channel state."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create channel_states table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS channel_states (
                    channel_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL DEFAULT 'collaborative',
                    jira_project TEXT,
                    default_epic TEXT,
                    workitem_ids JSONB DEFAULT '[]',
                    commit_ids JSONB DEFAULT '[]',
                    artifact_ids JSONB DEFAULT '[]',
                    active_threads JSONB DEFAULT '[]',
                    last_activity_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await self._conn.commit()

    async def get(self, channel_id: str) -> Optional[ChannelState]:
        """Get channel state, creating if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM channel_states WHERE channel_id = %s",
                (channel_id,),
            )
            row = await cur.fetchone()

        if not row:
            return await self._create_default(channel_id)

        return ChannelState(
            channel_id=row[0],
            mode=row[1],
            jira_project=row[2],
            default_epic=row[3],
            workitem_ids=row[4] or [],
            commit_ids=row[5] or [],
            artifact_ids=row[6] or [],
            active_threads=row[7] or [],
            last_activity_at=row[8],
        )

    async def _create_default(self, channel_id: str) -> ChannelState:
        """Create default channel state."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO channel_states (channel_id)
                VALUES (%s)
                ON CONFLICT (channel_id) DO NOTHING
                RETURNING *
                """,
                (channel_id,),
            )
            await self._conn.commit()

        return ChannelState(channel_id=channel_id)

    async def update(self, state: ChannelState) -> ChannelState:
        """Update channel state."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_states SET
                    mode = %s,
                    jira_project = %s,
                    default_epic = %s,
                    workitem_ids = %s,
                    commit_ids = %s,
                    artifact_ids = %s,
                    active_threads = %s,
                    last_activity_at = %s,
                    updated_at = %s
                WHERE channel_id = %s
                """,
                (
                    state.mode,
                    state.jira_project,
                    state.default_epic,
                    state.workitem_ids,
                    state.commit_ids,
                    state.artifact_ids,
                    state.active_threads,
                    state.last_activity_at or now,
                    now,
                    state.channel_id,
                ),
            )
            await self._conn.commit()

        return state

    async def add_workitem(self, channel_id: str, workitem_id: str) -> None:
        """Add workitem to channel registry."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_states
                SET workitem_ids = workitem_ids || %s::jsonb,
                    updated_at = NOW()
                WHERE channel_id = %s
                AND NOT workitem_ids @> %s::jsonb
                """,
                (f'["{workitem_id}"]', channel_id, f'["{workitem_id}"]'),
            )
            await self._conn.commit()

    async def add_commit(self, channel_id: str, commit_id: str) -> None:
        """Add commit to channel log."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_states
                SET commit_ids = commit_ids || %s::jsonb,
                    updated_at = NOW()
                WHERE channel_id = %s
                """,
                (f'["{commit_id}"]', channel_id),
            )
            await self._conn.commit()

    async def add_artifact(self, channel_id: str, artifact_id: str) -> None:
        """Add artifact to channel."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_states
                SET artifact_ids = artifact_ids || %s::jsonb,
                    updated_at = NOW()
                WHERE channel_id = %s
                AND NOT artifact_ids @> %s::jsonb
                """,
                (f'["{artifact_id}"]', channel_id, f'["{artifact_id}"]'),
            )
            await self._conn.commit()
