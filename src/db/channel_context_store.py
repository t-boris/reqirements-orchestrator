"""Channel context store with async CRUD operations using psycopg v3.

Provides database persistence for channel-level context with 4 layers:
- Layer 1: ChannelConfig (manual settings)
- Layer 2: ChannelKnowledge (pinned content)
- Layer 3: ChannelActivitySnapshot (live activity)
- Layer 4: Derived signals (computed, TTL-based)
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.db.models import (
    ChannelActivitySnapshot,
    ChannelConfig,
    ChannelContext,
    ChannelKnowledge,
)


class ChannelContextStore:
    """Async CRUD for channel context using raw SQL.

    Usage:
        async with get_connection() as conn:
            store = ChannelContextStore(conn)
            ctx = await store.get_or_create(team_id, channel_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create channel_context table with migration for existing.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS channel_context (
                    id UUID PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    config_json JSONB DEFAULT '{}',
                    knowledge_json JSONB DEFAULT '{}',
                    activity_json JSONB DEFAULT '{}',
                    derived_json JSONB DEFAULT '{}',
                    version INT DEFAULT 1,
                    pinned_digest TEXT,
                    jira_sync_cursor TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(team_id, channel_id)
                )
            """)

            # Add new columns if they don't exist (migration for existing tables)
            await cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'team_id'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN team_id TEXT NOT NULL DEFAULT '';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'config_json'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN config_json JSONB DEFAULT '{}';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'knowledge_json'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN knowledge_json JSONB DEFAULT '{}';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'activity_json'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN activity_json JSONB DEFAULT '{}';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'derived_json'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN derived_json JSONB DEFAULT '{}';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'version'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN version INT DEFAULT 1;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'pinned_digest'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN pinned_digest TEXT;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'jira_sync_cursor'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN jira_sync_cursor TEXT;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'created_at'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'channel_context' AND column_name = 'updated_at'
                    ) THEN
                        ALTER TABLE channel_context ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
                    END IF;
                END $$;
            """)

            await self._conn.commit()

    def _row_to_context(self, row: tuple) -> ChannelContext:
        """Convert database row to ChannelContext model.

        Args:
            row: Tuple from database query with columns:
                 id, team_id, channel_id, config_json, knowledge_json,
                 activity_json, derived_json, version, pinned_digest,
                 jira_sync_cursor, created_at, updated_at

        Returns:
            ChannelContext: Parsed model instance.
        """
        config_data = row[3] if row[3] else {}
        knowledge_data = row[4] if row[4] else {}
        activity_data = row[5] if row[5] else {}
        derived_data = row[6] if row[6] else {}

        return ChannelContext(
            id=str(row[0]),
            team_id=row[1],
            channel_id=row[2],
            config=ChannelConfig(**config_data),
            knowledge=ChannelKnowledge(**knowledge_data),
            activity=ChannelActivitySnapshot(**activity_data),
            derived_signals=derived_data,
            version=row[7] or 1,
            pinned_digest=row[8],
            jira_sync_cursor=row[9],
            created_at=row[10],
            updated_at=row[11],
        )

    async def get_or_create(self, team_id: str, channel_id: str) -> ChannelContext:
        """Get existing context or create empty one.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.

        Returns:
            ChannelContext: Existing or newly created context.
        """
        existing = await self.get_by_channel(team_id, channel_id)
        if existing:
            return existing

        # Create new context
        context_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO channel_context (
                    id, team_id, channel_id, config_json, knowledge_json,
                    activity_json, derived_json, version, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, team_id, channel_id, config_json, knowledge_json,
                          activity_json, derived_json, version, pinned_digest,
                          jira_sync_cursor, created_at, updated_at
                """,
                (
                    context_id,
                    team_id,
                    channel_id,
                    json.dumps({}),
                    json.dumps({}),
                    json.dumps({}),
                    json.dumps({}),
                    1,
                    now,
                    now,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_context(row)

    async def get_by_channel(
        self, team_id: str, channel_id: str
    ) -> Optional[ChannelContext]:
        """Get context if exists.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.

        Returns:
            ChannelContext if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, team_id, channel_id, config_json, knowledge_json,
                       activity_json, derived_json, version, pinned_digest,
                       jira_sync_cursor, created_at, updated_at
                FROM channel_context
                WHERE team_id = %s AND channel_id = %s
                """,
                (team_id, channel_id),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_context(row)

    async def update_config(
        self, team_id: str, channel_id: str, config: ChannelConfig
    ) -> ChannelContext:
        """Update Layer 1 config.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.
            config: New configuration.

        Returns:
            ChannelContext: Updated context.

        Raises:
            ValueError: If context not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_context
                SET config_json = %s, updated_at = %s
                WHERE team_id = %s AND channel_id = %s
                RETURNING id, team_id, channel_id, config_json, knowledge_json,
                          activity_json, derived_json, version, pinned_digest,
                          jira_sync_cursor, created_at, updated_at
                """,
                (json.dumps(config.model_dump()), now, team_id, channel_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Context not found: {team_id}/{channel_id}")

        return self._row_to_context(row)

    async def update_knowledge(
        self,
        team_id: str,
        channel_id: str,
        knowledge: ChannelKnowledge,
        pinned_digest: str,
    ) -> ChannelContext:
        """Update Layer 2 knowledge with new pinned_digest.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.
            knowledge: New knowledge extracted from pins.
            pinned_digest: Hash of pinned content for idempotency.

        Returns:
            ChannelContext: Updated context.

        Raises:
            ValueError: If context not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_context
                SET knowledge_json = %s, pinned_digest = %s, updated_at = %s
                WHERE team_id = %s AND channel_id = %s
                RETURNING id, team_id, channel_id, config_json, knowledge_json,
                          activity_json, derived_json, version, pinned_digest,
                          jira_sync_cursor, created_at, updated_at
                """,
                (json.dumps(knowledge.model_dump()), pinned_digest, now, team_id, channel_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Context not found: {team_id}/{channel_id}")

        return self._row_to_context(row)

    async def update_activity(
        self, team_id: str, channel_id: str, activity: ChannelActivitySnapshot
    ) -> ChannelContext:
        """Update Layer 3 activity snapshot.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.
            activity: New activity snapshot.

        Returns:
            ChannelContext: Updated context.

        Raises:
            ValueError: If context not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_context
                SET activity_json = %s, updated_at = %s
                WHERE team_id = %s AND channel_id = %s
                RETURNING id, team_id, channel_id, config_json, knowledge_json,
                          activity_json, derived_json, version, pinned_digest,
                          jira_sync_cursor, created_at, updated_at
                """,
                (json.dumps(activity.model_dump(), default=str), now, team_id, channel_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Context not found: {team_id}/{channel_id}")

        return self._row_to_context(row)

    async def update_derived(
        self, team_id: str, channel_id: str, derived: dict
    ) -> ChannelContext:
        """Update Layer 4 derived signals.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.
            derived: New derived signals.

        Returns:
            ChannelContext: Updated context.

        Raises:
            ValueError: If context not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_context
                SET derived_json = %s, updated_at = %s
                WHERE team_id = %s AND channel_id = %s
                RETURNING id, team_id, channel_id, config_json, knowledge_json,
                          activity_json, derived_json, version, pinned_digest,
                          jira_sync_cursor, created_at, updated_at
                """,
                (json.dumps(derived), now, team_id, channel_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Context not found: {team_id}/{channel_id}")

        return self._row_to_context(row)

    async def bump_version(self, team_id: str, channel_id: str) -> int:
        """Increment version and return new value.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.

        Returns:
            int: New version number.

        Raises:
            ValueError: If context not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE channel_context
                SET version = version + 1, updated_at = %s
                WHERE team_id = %s AND channel_id = %s
                RETURNING version
                """,
                (now, team_id, channel_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"Context not found: {team_id}/{channel_id}")

        return row[0]

    async def list_channels(self, team_id: str) -> list[ChannelContext]:
        """List all channels with context for a team.

        Args:
            team_id: Slack team/workspace ID.

        Returns:
            List of ChannelContext for the team.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, team_id, channel_id, config_json, knowledge_json,
                       activity_json, derived_json, version, pinned_digest,
                       jira_sync_cursor, created_at, updated_at
                FROM channel_context
                WHERE team_id = %s
                ORDER BY updated_at DESC
                """,
                (team_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_context(row) for row in rows]

    async def needs_pin_refresh(
        self, team_id: str, channel_id: str, current_digest: str
    ) -> bool:
        """Check if pins need re-extraction based on digest.

        Compares the current digest (computed from fresh pins) against
        the stored digest. If they differ, pins have changed and need
        re-extraction.

        Args:
            team_id: Slack team/workspace ID.
            channel_id: Slack channel ID.
            current_digest: Digest computed from current pins.

        Returns:
            True if digest changed or context doesn't exist.
        """
        ctx = await self.get_by_channel(team_id, channel_id)
        if not ctx:
            return True
        return ctx.pinned_digest != current_digest

    def is_stale_knowledge(self, ctx: ChannelContext, stale_months: int = 3) -> bool:
        """Check if pinned knowledge might be stale.

        Knowledge is considered stale if it was last updated more than
        the specified number of months ago. This allows prompting users
        to refresh their pinned channel rules.

        Args:
            ctx: Channel context.
            stale_months: How many months before suggesting refresh.

        Returns:
            True if knowledge last updated > stale_months ago.
        """
        if not ctx.knowledge.source_pin_ids:
            return False  # No knowledge to be stale
        if not ctx.updated_at:
            return True
        age = datetime.now(timezone.utc) - ctx.updated_at
        return age.days > (stale_months * 30)
