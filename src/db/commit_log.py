"""Commit log schema for event sourcing - Phase 32 Product Invariants.

INVARIANT I3: COMMIT_LOG_APPEND_ONLY
- Entries are NEVER modified after creation
- Entries are NEVER deleted
- Canonical messages can be rebuilt from log at any time
- On conflict, commit log wins

This is the authoritative event source for the system.

Migration (run via alembic):

CREATE TABLE commit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    action TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',

    -- Append-only enforcement at DB level
    -- No UPDATE or DELETE triggers would be added in prod
);

CREATE INDEX idx_commit_log_entity ON commit_log(entity_type, entity_id);
CREATE INDEX idx_commit_log_channel ON commit_log(channel_id, timestamp DESC);
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from src.schemas.invariants import CommitLogMutation


class CommitLogAction(str, Enum):
    """Actions that produce commit log entries.

    These are the significant events that become channel truth.
    Each action creates an immutable record in the commit log.
    """

    # Decision actions
    DECISION_CREATE = "decision_create"
    DECISION_APPROVE = "decision_approve"
    DECISION_DEPRECATE = "decision_deprecate"
    DECISION_REPLACE = "decision_replace"

    # WorkItem actions
    WORKITEM_CREATE = "workitem_create"
    WORKITEM_APPROVE = "workitem_approve"
    WORKITEM_UPDATE = "workitem_update"
    WORKITEM_PUBLISH = "workitem_publish"

    # Draft actions
    DRAFT_CREATE = "draft_create"
    DRAFT_TRANSFORM = "draft_transform"
    DRAFT_COMMIT = "draft_commit"

    # Link actions
    LINK_CREATE = "link_create"
    LINK_REMOVE = "link_remove"

    # Override actions (audit trail)
    OVERRIDE_GRANTED = "override_granted"
    OVERRIDE_USED = "override_used"


@dataclass
class CommitLogEntry:
    """Immutable commit log entry.

    INVARIANT I3: COMMIT_LOG_APPEND_ONLY
    - Entries are NEVER modified after creation
    - Entries are NEVER deleted
    - Canonical messages can be rebuilt from log at any time
    - On conflict, commit log wins

    This is the authoritative event source. All significant events
    are recorded here with full entity snapshots.

    Immutability is enforced via __setattr__ override - any attempt
    to modify fields after construction raises CommitLogMutation.

    Attributes:
        id: UUID for this entry.
        channel_id: Slack channel where event occurred.
        entity_type: Type of entity (decision, workitem, draft).
        entity_id: UUID of the entity.
        action: What happened (see CommitLogAction).
        actor_user_id: User who performed the action.
        timestamp: When the action occurred.
        snapshot: Full entity state at commit time (JSON-serializable).
        metadata: Additional context (JSON-serializable).
    """

    id: str
    channel_id: str
    entity_type: Literal["decision", "workitem", "draft"]
    entity_id: str
    action: CommitLogAction
    actor_user_id: str
    timestamp: datetime
    snapshot: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    # Immutability marker - set after __init__ completes
    _frozen: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """Freeze the instance after construction."""
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent modification of frozen entries.

        INVARIANT: Commit log entries are immutable after creation.

        Raises:
            CommitLogMutation: If attempting to modify a frozen entry.
        """
        if getattr(self, "_frozen", False) and name != "_frozen":
            raise CommitLogMutation(
                f"COMMIT_LOG_APPEND_ONLY: Cannot modify commit log entry field: {name}",
                {"entry_id": self.id, "field": name},
            )
        object.__setattr__(self, name, value)

    @classmethod
    def create(
        cls,
        channel_id: str,
        entity_type: Literal["decision", "workitem", "draft"],
        entity_id: str,
        action: CommitLogAction,
        actor_user_id: str,
        snapshot: dict[str, Any],
        metadata: Optional[dict[str, Any]] = None,
    ) -> "CommitLogEntry":
        """Create a new commit log entry.

        This is the only way to create entries - ensures all required
        fields are provided and timestamps are consistent.

        Args:
            channel_id: Slack channel ID.
            entity_type: Type of entity being logged.
            entity_id: UUID of the entity.
            action: The action that occurred.
            actor_user_id: User who performed the action.
            snapshot: Full entity state at this point in time.
            metadata: Additional context (optional).

        Returns:
            A new immutable CommitLogEntry.
        """
        return cls(
            id=str(uuid4()),
            channel_id=channel_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_user_id=actor_user_id,
            timestamp=datetime.utcnow(),
            snapshot=snapshot,
            metadata=metadata or {},
        )


class CommitLogStore:
    """Append-only commit log store.

    INVARIANT: No update or delete methods.
    Only append() and query methods exist.

    This store provides:
    - append(): Add new entries to the log
    - get_by_entity(): Get full history for an entity
    - get_latest_snapshot(): Rebuild current state from log
    - get_by_channel(): Get channel activity (for commit log UI)

    The store deliberately omits:
    - update() - entries are immutable
    - delete() - entries are permanent
    - mark_deleted() - soft delete is still delete

    Usage:
        async with get_connection() as conn:
            store = CommitLogStore(conn)

            # Append new entry
            entry = CommitLogEntry.create(
                channel_id=channel,
                entity_type="decision",
                entity_id=decision_id,
                action=CommitLogAction.DECISION_APPROVE,
                actor_user_id=user_id,
                snapshot=decision.model_dump(),
            )
            await store.append(entry)

            # Query history
            history = await store.get_by_entity("decision", decision_id)
    """

    def __init__(self, conn: Any) -> None:
        """Initialize with database connection.

        Args:
            conn: AsyncConnection from psycopg.
        """
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create commit_log table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS event_commit_log (
                    id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id UUID NOT NULL,
                    action TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    snapshot JSONB NOT NULL,
                    metadata JSONB DEFAULT '{}'
                )
            """)

            # Index for entity history queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_commit_log_entity
                ON event_commit_log(entity_type, entity_id, timestamp DESC)
            """)

            # Index for channel activity queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_commit_log_channel
                ON event_commit_log(channel_id, timestamp DESC)
            """)

            await self._conn.commit()

    async def append(self, entry: CommitLogEntry) -> None:
        """Append entry to log. Only write operation allowed.

        INVARIANT: This is INSERT only, never UPDATE.

        Args:
            entry: The commit log entry to append.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO event_commit_log
                    (id, channel_id, entity_type, entity_id, action,
                     actor_user_id, timestamp, snapshot, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    entry.id,
                    entry.channel_id,
                    entry.entity_type,
                    entry.entity_id,
                    entry.action.value,
                    entry.actor_user_id,
                    entry.timestamp,
                    entry.snapshot,
                    entry.metadata,
                ),
            )
            await self._conn.commit()

    async def get_by_entity(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[CommitLogEntry]:
        """Get all entries for an entity (full history).

        Returns entries ordered by timestamp ascending (oldest first)
        to show the full evolution of the entity.

        Args:
            entity_type: Type of entity (decision, workitem, draft).
            entity_id: UUID of the entity.

        Returns:
            List of CommitLogEntry objects, oldest first.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, entity_type, entity_id, action,
                       actor_user_id, timestamp, snapshot, metadata
                FROM event_commit_log
                WHERE entity_type = %s AND entity_id = %s
                ORDER BY timestamp ASC
                """,
                (entity_type, entity_id),
            )
            rows = await cur.fetchall()

        return [self._row_to_entry(row) for row in rows]

    async def get_latest_snapshot(
        self,
        entity_type: str,
        entity_id: str,
    ) -> Optional[dict[str, Any]]:
        """Get most recent snapshot for rebuilding canonical state.

        Returns the snapshot from the most recent commit log entry,
        which represents the current state of the entity.

        Args:
            entity_type: Type of entity.
            entity_id: UUID of the entity.

        Returns:
            The snapshot dict, or None if no entries exist.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT snapshot
                FROM event_commit_log
                WHERE entity_type = %s AND entity_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (entity_type, entity_id),
            )
            row = await cur.fetchone()

        if not row:
            return None
        return row[0]

    async def get_by_channel(
        self,
        channel_id: str,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[CommitLogEntry]:
        """Get entries for channel (for channel log view).

        Returns entries ordered by timestamp descending (newest first)
        for display in the channel commit log UI.

        Args:
            channel_id: Slack channel ID.
            since: Optional cutoff timestamp (only entries after this).
            limit: Maximum entries to return (default 50).

        Returns:
            List of CommitLogEntry objects, newest first.
        """
        if since:
            query = """
                SELECT id, channel_id, entity_type, entity_id, action,
                       actor_user_id, timestamp, snapshot, metadata
                FROM event_commit_log
                WHERE channel_id = %s AND timestamp > %s
                ORDER BY timestamp DESC
                LIMIT %s
            """
            params = (channel_id, since, limit)
        else:
            query = """
                SELECT id, channel_id, entity_type, entity_id, action,
                       actor_user_id, timestamp, snapshot, metadata
                FROM event_commit_log
                WHERE channel_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """
            params = (channel_id, limit)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_entry(row) for row in rows]

    async def get_by_action(
        self,
        channel_id: str,
        action: CommitLogAction,
        limit: int = 50,
    ) -> list[CommitLogEntry]:
        """Get entries by action type for a channel.

        Useful for filtering specific types of events (e.g., all decisions).

        Args:
            channel_id: Slack channel ID.
            action: The action type to filter by.
            limit: Maximum entries to return.

        Returns:
            List of CommitLogEntry objects matching the action.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, entity_type, entity_id, action,
                       actor_user_id, timestamp, snapshot, metadata
                FROM event_commit_log
                WHERE channel_id = %s AND action = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (channel_id, action.value, limit),
            )
            rows = await cur.fetchall()

        return [self._row_to_entry(row) for row in rows]

    # NO update() method - INVARIANT: entries are immutable
    # NO delete() method - INVARIANT: entries are permanent
    # NO mark_deleted() method - soft delete is still delete

    def _row_to_entry(self, row: tuple) -> CommitLogEntry:
        """Convert database row to CommitLogEntry.

        Note: We use object.__setattr__ to bypass the frozen check
        since we're reconstructing from database, not modifying.
        """
        entry = object.__new__(CommitLogEntry)
        object.__setattr__(entry, "id", str(row[0]))
        object.__setattr__(entry, "channel_id", row[1])
        object.__setattr__(entry, "entity_type", row[2])
        object.__setattr__(entry, "entity_id", str(row[3]))
        object.__setattr__(entry, "action", CommitLogAction(row[4]))
        object.__setattr__(entry, "actor_user_id", row[5])
        object.__setattr__(entry, "timestamp", row[6])
        object.__setattr__(entry, "snapshot", row[7] or {})
        object.__setattr__(entry, "metadata", row[8] or {})
        object.__setattr__(entry, "_frozen", True)
        return entry


# =============================================================================
# Export all types for easy import
# =============================================================================

__all__ = [
    "CommitLogAction",
    "CommitLogEntry",
    "CommitLogStore",
]
