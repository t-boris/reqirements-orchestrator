"""Conflict store for multi-user draft conflicts (Phase 27.3).

Persists draft conflicts until resolved. Supports:
- Creating conflicts when contradictions detected
- Querying unresolved conflicts for a thread
- Recording resolutions with user attribution

Phase 27.3 - Multi-Author Drafts & Conflict Detection
"""
from datetime import datetime, timezone
from typing import Optional
import json
from psycopg import AsyncConnection

from src.schemas.conflict import DraftConflict, ConflictType, ConflictSide
from src.schemas.attribution import MessageAttribution


class ConflictStore:
    """Store and manage draft conflicts.

    Conflicts are created when contradicting information is detected
    between different users' contributions. They persist until explicitly
    resolved by a user.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create draft_conflicts table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS draft_conflicts (
                    conflict_id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    conflict_type TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    existing_data JSONB NOT NULL,
                    proposed_data JSONB NOT NULL,
                    resolved BOOLEAN DEFAULT FALSE,
                    resolution TEXT,
                    resolved_by TEXT,
                    resolved_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_draft_conflicts_thread
                ON draft_conflicts(channel_id, thread_ts)
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_draft_conflicts_unresolved
                ON draft_conflicts(channel_id, thread_ts) WHERE resolved = FALSE
            """)
            await self._conn.commit()

    async def create(
        self,
        channel_id: str,
        thread_ts: str,
        conflict: DraftConflict,
    ) -> DraftConflict:
        """Store a new conflict.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp
            conflict: The DraftConflict to store

        Returns:
            The stored DraftConflict
        """
        now = datetime.now(timezone.utc)

        # Serialize ConflictSide to JSONB
        existing_data = {
            "content": conflict.existing.content,
            "attribution": conflict.existing.attribution.model_dump(),
            "label": conflict.existing.label,
        }
        proposed_data = {
            "content": conflict.proposed.content,
            "attribution": conflict.proposed.attribution.model_dump(),
            "label": conflict.proposed.label,
        }

        async with self._conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO draft_conflicts
                    (conflict_id, channel_id, thread_ts, conflict_type, field_name,
                     description, existing_data, proposed_data, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                conflict.conflict_id,
                channel_id,
                thread_ts,
                conflict.conflict_type.value,
                conflict.field_name,
                conflict.description,
                json.dumps(existing_data),
                json.dumps(proposed_data),
                now,
            ))
            await self._conn.commit()
        return conflict

    async def get(self, conflict_id: str) -> Optional[DraftConflict]:
        """Get conflict by ID.

        Args:
            conflict_id: UUID of the conflict

        Returns:
            DraftConflict if found, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM draft_conflicts WHERE conflict_id = %s
            """, (conflict_id,))
            row = await cur.fetchone()
        return self._row_to_model(row) if row else None

    async def get_unresolved(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> list[DraftConflict]:
        """Get unresolved conflicts for a thread.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp

        Returns:
            List of unresolved DraftConflict records, newest first
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM draft_conflicts
                WHERE channel_id = %s AND thread_ts = %s AND resolved = FALSE
                ORDER BY created_at DESC
            """, (channel_id, thread_ts))
            rows = await cur.fetchall()
        return [self._row_to_model(row) for row in rows]

    async def get_all(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> list[DraftConflict]:
        """Get all conflicts for a thread (including resolved).

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp

        Returns:
            List of all DraftConflict records, newest first
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM draft_conflicts
                WHERE channel_id = %s AND thread_ts = %s
                ORDER BY created_at DESC
            """, (channel_id, thread_ts))
            rows = await cur.fetchall()
        return [self._row_to_model(row) for row in rows]

    async def resolve(
        self,
        conflict_id: str,
        resolution: str,
        resolved_by: str,
    ) -> Optional[DraftConflict]:
        """Mark conflict as resolved.

        Args:
            conflict_id: UUID of the conflict
            resolution: Which side was chosen ('existing' or 'proposed')
            resolved_by: User ID who resolved

        Returns:
            Updated DraftConflict, or None if not found
        """
        now = datetime.now(timezone.utc)
        async with self._conn.cursor() as cur:
            await cur.execute("""
                UPDATE draft_conflicts
                SET resolved = TRUE, resolution = %s, resolved_by = %s, resolved_at = %s
                WHERE conflict_id = %s
                RETURNING *
            """, (resolution, resolved_by, now, conflict_id))
            row = await cur.fetchone()
            await self._conn.commit()
        return self._row_to_model(row) if row else None

    async def has_unresolved_conflicts(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Check if thread has any unresolved conflicts.

        Useful for blocking draft progress until conflicts resolved.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp

        Returns:
            True if unresolved conflicts exist
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM draft_conflicts
                    WHERE channel_id = %s AND thread_ts = %s AND resolved = FALSE
                )
            """, (channel_id, thread_ts))
            row = await cur.fetchone()
        return row[0] if row else False

    async def count_unresolved(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> int:
        """Count unresolved conflicts for a thread.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp

        Returns:
            Number of unresolved conflicts
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT COUNT(*) FROM draft_conflicts
                WHERE channel_id = %s AND thread_ts = %s AND resolved = FALSE
            """, (channel_id, thread_ts))
            row = await cur.fetchone()
        return row[0] if row else 0

    def _row_to_model(self, row: tuple) -> DraftConflict:
        """Convert database row to DraftConflict model."""
        # Parse JSONB columns
        existing_data = row[6] if isinstance(row[6], dict) else json.loads(row[6])
        proposed_data = row[7] if isinstance(row[7], dict) else json.loads(row[7])

        # Reconstruct ConflictSide objects
        existing = ConflictSide(
            content=existing_data["content"],
            attribution=MessageAttribution(**existing_data["attribution"]),
            label=existing_data.get("label", ""),
        )
        proposed = ConflictSide(
            content=proposed_data["content"],
            attribution=MessageAttribution(**proposed_data["attribution"]),
            label=proposed_data.get("label", ""),
        )

        return DraftConflict(
            conflict_id=str(row[0]),
            conflict_type=ConflictType(row[3]),
            field_name=row[4],
            description=row[5],
            existing=existing,
            proposed=proposed,
            resolved=row[8],
            resolution=row[9],
            resolved_by=row[10],
            resolved_at=row[11].isoformat() if row[11] else None,
        )
