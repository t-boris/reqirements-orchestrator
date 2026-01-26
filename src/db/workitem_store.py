"""WorkItem store with async CRUD operations using psycopg v3.

Provides database persistence for work items in the channel registry.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from psycopg import AsyncConnection

from src.db.models import WorkItem, WorkItemStatus, WorkItemType


class WorkItemStore:
    """Async CRUD operations for WorkItems.

    Usage:
        async with get_connection() as conn:
            store = WorkItemStore(conn)
            item = await store.create(channel_id, WorkItemType.STORY, "Add retry logic", user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create work_items table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS work_items (
                    id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',

                    -- Content
                    summary TEXT NOT NULL,
                    description TEXT,
                    facts JSONB DEFAULT '{}',

                    -- Jira linkage
                    jira_key TEXT,
                    jira_sync_at TIMESTAMPTZ,
                    jira_fingerprint JSONB,

                    -- Hierarchy
                    parent_id UUID,

                    -- Provenance
                    source_thread_ts TEXT,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),

                    -- Ownership (Phase 27.5)
                    owners TEXT[] DEFAULT '{}',
                    watchers TEXT[] DEFAULT '{}',
                    last_updated_by TEXT,

                    -- Readiness
                    readiness_score REAL DEFAULT 0.0
                )
            """)

            # Migration: Add ownership columns to existing table
            await cur.execute("""
                ALTER TABLE work_items
                ADD COLUMN IF NOT EXISTS owners TEXT[] DEFAULT '{}',
                ADD COLUMN IF NOT EXISTS watchers TEXT[] DEFAULT '{}',
                ADD COLUMN IF NOT EXISTS last_updated_by TEXT
            """)

            # Migration: Add canonical message tracking (Phase 33)
            await cur.execute("""
                ALTER TABLE work_items
                ADD COLUMN IF NOT EXISTS canonical_message_ts TEXT,
                ADD COLUMN IF NOT EXISTS canonical_channel_id TEXT
            """)

            # Index on channel_id for list queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_work_items_channel_id
                ON work_items(channel_id)
            """)

            # Index on jira_key for sync lookups
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_work_items_jira_key
                ON work_items(jira_key)
                WHERE jira_key IS NOT NULL
            """)

            # Index on parent_id for hierarchy queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_work_items_parent_id
                ON work_items(parent_id)
                WHERE parent_id IS NOT NULL
            """)

            # Index on canonical message for anchor lookups (Phase 33)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_work_items_canonical
                ON work_items(canonical_channel_id, canonical_message_ts)
                WHERE canonical_message_ts IS NOT NULL
            """)

            await self._conn.commit()

    async def create(
        self,
        channel_id: str,
        item_type: WorkItemType,
        summary: str,
        created_by: str,
        *,
        description: str | None = None,
        parent_id: str | None = None,
        source_thread_ts: str | None = None,
    ) -> WorkItem:
        """Create a new draft work item.

        Args:
            channel_id: Slack channel ID.
            item_type: Type of work item (EPIC, STORY, etc.).
            summary: Title/summary of the work item.
            created_by: User ID who created the item.
            description: Optional full description.
            parent_id: Optional parent WorkItem UUID.
            source_thread_ts: Optional thread timestamp that created this item.

        Returns:
            WorkItem: Newly created work item with DRAFT status.
            Owner is automatically set to the creator.
        """
        item_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        # Creator becomes first owner
        owners = [created_by]

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO work_items (
                    id, channel_id, item_type, status, summary, description,
                    parent_id, source_thread_ts, created_by, created_at, updated_at,
                    owners, watchers, last_updated_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, channel_id, item_type, status, summary, description,
                          facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                          source_thread_ts, created_by, created_at, updated_at,
                          owners, watchers, last_updated_by, readiness_score,
                          canonical_message_ts, canonical_channel_id
                """,
                (
                    item_id,
                    channel_id,
                    item_type.value,
                    WorkItemStatus.DRAFT.value,
                    summary,
                    description,
                    parent_id,
                    source_thread_ts,
                    created_by,
                    now,
                    now,
                    owners,
                    [],  # Empty watchers initially
                    created_by,  # Creator is last_updated_by
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_workitem(row)

    async def get(self, item_id: str) -> WorkItem | None:
        """Get work item by ID.

        Args:
            item_id: UUID of the work item.

        Returns:
            WorkItem if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, item_type, status, summary, description,
                       facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                       source_thread_ts, created_by, created_at, updated_at,
                       owners, watchers, last_updated_by, readiness_score,
                          canonical_message_ts, canonical_channel_id
                FROM work_items
                WHERE id = %s
                """,
                (item_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_workitem(row)

    async def get_by_jira_key(self, jira_key: str) -> WorkItem | None:
        """Get work item by Jira key (for sync lookups).

        Delegates to WorkItemQueries.
        """
        from src.db.workitem_queries import WorkItemQueries

        queries = WorkItemQueries(self._conn)
        return await queries.get_by_jira_key(jira_key)

    async def list_by_channel(
        self,
        channel_id: str,
        *,
        status: list[WorkItemStatus] | None = None,
        item_type: WorkItemType | None = None,
        limit: int = 20,
    ) -> list[WorkItem]:
        """List work items for a channel with optional filters.

        Delegates to WorkItemQueries.
        """
        from src.db.workitem_queries import WorkItemQueries

        queries = WorkItemQueries(self._conn)
        return await queries.list_by_channel(
            channel_id, status=status, item_type=item_type, limit=limit
        )

    async def update(
        self,
        item_id: str,
        *,
        summary: str | None = None,
        description: str | None = None,
        status: WorkItemStatus | None = None,
        jira_key: str | None = None,
        jira_sync_at: datetime | None = None,
        jira_fingerprint: dict[str, str] | None = None,
        facts: dict[str, Any] | None = None,
        readiness_score: float | None = None,
        last_updated_by: str | None = None,
    ) -> WorkItem:
        """Update work item fields. Only non-None values are updated.

        Args:
            item_id: UUID of the work item to update.
            summary: New summary if provided.
            description: New description if provided.
            status: New status if provided.
            jira_key: New Jira key if provided.
            jira_sync_at: New sync timestamp if provided.
            jira_fingerprint: New fingerprint if provided.
            facts: New facts dict if provided.
            readiness_score: New readiness score if provided.
            last_updated_by: User ID who made this update.

        Returns:
            WorkItem: Updated work item.

        Raises:
            ValueError: If work item not found.
        """
        # Build dynamic SET clause
        set_clauses: list[str] = []
        params: list[Any] = []

        if summary is not None:
            set_clauses.append("summary = %s")
            params.append(summary)

        if description is not None:
            set_clauses.append("description = %s")
            params.append(description)

        if status is not None:
            set_clauses.append("status = %s")
            params.append(status.value)

        if jira_key is not None:
            set_clauses.append("jira_key = %s")
            params.append(jira_key)

        if jira_sync_at is not None:
            set_clauses.append("jira_sync_at = %s")
            params.append(jira_sync_at)

        if jira_fingerprint is not None:
            set_clauses.append("jira_fingerprint = %s")
            params.append(json.dumps(jira_fingerprint))

        if facts is not None:
            set_clauses.append("facts = %s")
            params.append(json.dumps(facts))

        if readiness_score is not None:
            set_clauses.append("readiness_score = %s")
            params.append(readiness_score)

        if last_updated_by is not None:
            set_clauses.append("last_updated_by = %s")
            params.append(last_updated_by)

        # Always update updated_at
        set_clauses.append("updated_at = %s")
        now = datetime.now(timezone.utc)
        params.append(now)

        # Add item_id for WHERE clause
        params.append(item_id)

        query = f"""
            UPDATE work_items
            SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING id, channel_id, item_type, status, summary, description,
                      facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                      source_thread_ts, created_by, created_at, updated_at,
                      owners, watchers, last_updated_by, readiness_score,
                          canonical_message_ts, canonical_channel_id
        """

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"WorkItem not found: {item_id}")

        return self._row_to_workitem(row)

    async def delete(self, item_id: str) -> bool:
        """Delete work item.

        Args:
            item_id: UUID of the work item to delete.

        Returns:
            True if deleted, False if not found.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM work_items WHERE id = %s RETURNING id",
                (item_id,),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    async def get_children(self, parent_id: str) -> list[WorkItem]:
        """Get child work items (stories under epic).

        Delegates to WorkItemQueries.
        """
        from src.db.workitem_queries import WorkItemQueries

        queries = WorkItemQueries(self._conn)
        return await queries.get_children(parent_id)

    def calculate_readiness(self, item: WorkItem) -> float:
        """Calculate readiness score for a work item.

        Scoring (0.0 to 1.0):
        - 0.2: Has summary (always true if item exists)
        - 0.3: Has description
        - 0.2: Has facts/constraints captured
        - 0.2: Has parent_id OR is Epic type
        - 0.1: Has source_thread_ts (provenance)

        Returns:
            float: Score from 0.0 to 1.0 indicating draft completeness.
        """
        score = 0.0

        # Summary is required, so always present
        if item.summary:
            score += 0.2

        # Description adds significant value
        if item.description:
            score += 0.3

        # Facts/constraints captured
        if item.facts and len(item.facts) > 0:
            score += 0.2

        # Hierarchy established (parent set or is top-level Epic)
        if item.parent_id or item.item_type == WorkItemType.EPIC:
            score += 0.2

        # Provenance tracked
        if item.source_thread_ts:
            score += 0.1

        return min(score, 1.0)

    async def refresh_readiness(self, item_id: str) -> WorkItem:
        """Recalculate and persist readiness score for a work item.

        Args:
            item_id: UUID of the work item.

        Returns:
            WorkItem: Updated work item with new readiness score.

        Raises:
            ValueError: If work item not found.
        """
        item = await self.get(item_id)
        if not item:
            raise ValueError(f"WorkItem not found: {item_id}")

        new_score = self.calculate_readiness(item)
        return await self.update(item_id, readiness_score=new_score)

    def _row_to_workitem(self, row: tuple) -> WorkItem:
        """Convert database row to WorkItem model.

        Args:
            row: Tuple from database query.
                Expected order (21 columns):
                0: id, 1: channel_id, 2: item_type, 3: status,
                4: summary, 5: description, 6: facts,
                7: jira_key, 8: jira_sync_at, 9: jira_fingerprint,
                10: parent_id, 11: source_thread_ts, 12: created_by,
                13: created_at, 14: updated_at,
                15: owners, 16: watchers, 17: last_updated_by,
                18: readiness_score,
                19: canonical_message_ts, 20: canonical_channel_id

        Returns:
            WorkItem model instance.
        """
        # Parse JSONB fields
        facts = row[6] if row[6] else {}
        jira_fingerprint = row[9] if row[9] else None
        # Parse ownership arrays (may be None for older records)
        owners = list(row[15]) if row[15] else []
        watchers = list(row[16]) if row[16] else []
        last_updated_by = row[17] if row[17] else None

        return WorkItem(
            id=str(row[0]),
            channel_id=row[1],
            item_type=WorkItemType(row[2]),
            status=WorkItemStatus(row[3]),
            summary=row[4],
            description=row[5],
            facts=facts,
            jira_key=row[7],
            jira_sync_at=row[8],
            jira_fingerprint=jira_fingerprint,
            parent_id=str(row[10]) if row[10] else None,
            source_thread_ts=row[11],
            created_by=row[12],
            created_at=row[13],
            updated_at=row[14],
            owners=owners,
            watchers=watchers,
            last_updated_by=last_updated_by,
            readiness_score=row[18],
            canonical_message_ts=row[19] if row[19] else None,
            canonical_channel_id=row[20] if row[20] else None,
        )

    # -------------------------------------------------------------------------
    # Ownership operations (Phase 27.5)
    # -------------------------------------------------------------------------

    async def update_ownership(
        self,
        item_id: str,
        *,
        owners: list[str] | None = None,
        watchers: list[str] | None = None,
        last_updated_by: str | None = None,
    ) -> WorkItem:
        """Update ownership fields on a work item.

        Args:
            item_id: UUID of the work item to update.
            owners: New owners list if provided (replaces existing).
            watchers: New watchers list if provided (replaces existing).
            last_updated_by: User ID who made this update.

        Returns:
            WorkItem: Updated work item.

        Raises:
            ValueError: If work item not found.
        """
        set_clauses: list[str] = []
        params: list[Any] = []

        if owners is not None:
            set_clauses.append("owners = %s")
            params.append(owners)

        if watchers is not None:
            set_clauses.append("watchers = %s")
            params.append(watchers)

        if last_updated_by is not None:
            set_clauses.append("last_updated_by = %s")
            params.append(last_updated_by)

        if not set_clauses:
            # Nothing to update - return current item
            item = await self.get(item_id)
            if not item:
                raise ValueError(f"WorkItem not found: {item_id}")
            return item

        # Always update updated_at
        set_clauses.append("updated_at = %s")
        now = datetime.now(timezone.utc)
        params.append(now)

        params.append(item_id)

        query = f"""
            UPDATE work_items
            SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING id, channel_id, item_type, status, summary, description,
                      facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                      source_thread_ts, created_by, created_at, updated_at,
                      owners, watchers, last_updated_by, readiness_score,
                          canonical_message_ts, canonical_channel_id
        """

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"WorkItem not found: {item_id}")

        return self._row_to_workitem(row)

    async def add_owner(self, item_id: str, user_id: str) -> WorkItem:
        """Add a user to owners list (idempotent).

        Args:
            item_id: UUID of the work item.
            user_id: User ID to add as owner.

        Returns:
            WorkItem: Updated work item.

        Raises:
            ValueError: If work item not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            # Use array_append with CASE to avoid duplicates
            await cur.execute(
                """
                UPDATE work_items
                SET owners = CASE
                        WHEN %s = ANY(owners) THEN owners
                        ELSE array_append(owners, %s)
                    END,
                    updated_at = %s
                WHERE id = %s
                RETURNING id, channel_id, item_type, status, summary, description,
                          facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                          source_thread_ts, created_by, created_at, updated_at,
                          owners, watchers, last_updated_by, readiness_score,
                          canonical_message_ts, canonical_channel_id
                """,
                (user_id, user_id, now, item_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"WorkItem not found: {item_id}")

        return self._row_to_workitem(row)

    async def add_watcher(self, item_id: str, user_id: str) -> WorkItem:
        """Add a user to watchers list (idempotent).

        Args:
            item_id: UUID of the work item.
            user_id: User ID to add as watcher.

        Returns:
            WorkItem: Updated work item.

        Raises:
            ValueError: If work item not found.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            # Use array_append with CASE to avoid duplicates
            await cur.execute(
                """
                UPDATE work_items
                SET watchers = CASE
                        WHEN %s = ANY(watchers) THEN watchers
                        ELSE array_append(watchers, %s)
                    END,
                    updated_at = %s
                WHERE id = %s
                RETURNING id, channel_id, item_type, status, summary, description,
                          facts, jira_key, jira_sync_at, jira_fingerprint, parent_id,
                          source_thread_ts, created_by, created_at, updated_at,
                          owners, watchers, last_updated_by, readiness_score,
                          canonical_message_ts, canonical_channel_id
                """,
                (user_id, user_id, now, item_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            raise ValueError(f"WorkItem not found: {item_id}")

        return self._row_to_workitem(row)

    async def get_items_for_user(
        self,
        channel_id: str,
        user_id: str,
        role: Literal["owner", "watcher", "any"] = "any",
    ) -> list[WorkItem]:
        """Get work items where user is owner or watcher.

        Delegates to WorkItemQueries.
        """
        from src.db.workitem_queries import WorkItemQueries

        queries = WorkItemQueries(self._conn)
        return await queries.get_items_for_user(channel_id, user_id, role)

    # -------------------------------------------------------------------------
    # Anchor message operations (Phase 33)
    # -------------------------------------------------------------------------

    async def set_canonical_message(
        self,
        workitem_id: str,
        channel_id: str,
        message_ts: str,
    ) -> bool:
        """Set the canonical message for a WorkItem.

        Called after posting the anchor message to Slack.
        Also creates entry in AnchorStore for reverse lookup.

        Args:
            workitem_id: UUID of the work item.
            channel_id: Slack channel where anchor was posted.
            message_ts: The anchor message timestamp in Slack.

        Returns:
            True if updated successfully, False if workitem not found.
        """
        # Import here to avoid circular imports
        from src.db.anchor_store import AnchorStore
        from src.schemas.anchor import AnchorType

        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE work_items
                SET canonical_message_ts = %s,
                    canonical_channel_id = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING id
                """,
                (message_ts, channel_id, now, workitem_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            return False

        # Also register in AnchorStore for reverse lookup
        anchor_store = AnchorStore(self._conn)
        try:
            await anchor_store.create_anchor(
                anchor_type=AnchorType.WORKITEM,
                object_id=workitem_id,
                channel_id=channel_id,
                message_ts=message_ts,
                created_by="system",  # Will be updated with actual user in caller
            )
        except Exception:
            # Anchor may already exist (re-posting anchor) - update is fine
            pass

        return True

    async def get_by_canonical_message(
        self,
        channel_id: str,
        message_ts: str,
    ) -> WorkItem | None:
        """Lookup WorkItem by its canonical message.

        Delegates to WorkItemQueries.
        """
        from src.db.workitem_queries import WorkItemQueries

        queries = WorkItemQueries(self._conn)
        return await queries.get_by_canonical_message(channel_id, message_ts)
