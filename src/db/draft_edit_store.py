"""Draft edit tracking for multi-author drafts (Phase 27.3).

Tracks edit history for multi-author drafts, enabling:
- Attribution of each change to its author
- History of who changed what and when
- Contributor list for a draft

Phase 27.3 - Multi-Author Drafts & Conflict Detection
"""
from datetime import datetime, timezone
from typing import Optional
import uuid
from pydantic import BaseModel, Field
from psycopg import AsyncConnection


class DraftEdit(BaseModel):
    """Record of an edit to a draft field."""

    edit_id: str = Field(description="UUID for this edit")
    thread_ts: str = Field(description="Thread containing the draft")
    channel_id: str = Field(description="Channel ID")
    user_id: str = Field(description="User who made the edit")
    field_name: str = Field(description="Field that was changed")
    old_value: Optional[str] = Field(default=None, description="Previous value")
    new_value: str = Field(description="New value after edit")
    source_message_ts: str = Field(description="Message that triggered edit")
    edit_type: str = Field(default="update", description="add, update, delete")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DraftEditStore:
    """Track edit history for multi-author drafts.

    Provides full audit trail of who changed what in a draft,
    enabling conflict detection and attribution display.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create draft_edits table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS draft_edits (
                    edit_id UUID PRIMARY KEY,
                    thread_ts TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT NOT NULL,
                    source_message_ts TEXT NOT NULL,
                    edit_type TEXT DEFAULT 'update',
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_draft_edits_thread
                ON draft_edits(channel_id, thread_ts)
            """)
            await self._conn.commit()

    async def record_edit(
        self,
        thread_ts: str,
        channel_id: str,
        user_id: str,
        field_name: str,
        new_value: str,
        source_message_ts: str,
        old_value: Optional[str] = None,
        edit_type: str = "update",
    ) -> DraftEdit:
        """Record an edit to a draft field.

        Args:
            thread_ts: Thread timestamp
            channel_id: Channel ID
            user_id: User who made the edit
            field_name: Field that was changed
            new_value: New value after edit
            source_message_ts: Message that triggered edit
            old_value: Previous value (if known)
            edit_type: Type of edit (add, update, delete)

        Returns:
            The recorded DraftEdit
        """
        edit_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO draft_edits
                    (edit_id, thread_ts, channel_id, user_id, field_name,
                     old_value, new_value, source_message_ts, edit_type, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (edit_id, thread_ts, channel_id, user_id, field_name,
                  old_value, new_value, source_message_ts, edit_type, now))
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_model(row)

    async def get_edit_history(
        self,
        channel_id: str,
        thread_ts: str,
        field_name: Optional[str] = None,
    ) -> list[DraftEdit]:
        """Get edit history for a thread, optionally filtered by field.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp
            field_name: Optional field to filter by

        Returns:
            List of DraftEdit records, newest first
        """
        query = """
            SELECT * FROM draft_edits
            WHERE channel_id = %s AND thread_ts = %s
        """
        params: list = [channel_id, thread_ts]

        if field_name:
            query += " AND field_name = %s"
            params.append(field_name)

        query += " ORDER BY created_at DESC"

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_model(row) for row in rows]

    async def get_contributors(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> list[str]:
        """Get list of user IDs who contributed edits.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp

        Returns:
            List of unique user IDs who made edits
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT DISTINCT user_id FROM draft_edits
                WHERE channel_id = %s AND thread_ts = %s
            """, (channel_id, thread_ts))
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    async def get_last_edit_for_field(
        self,
        channel_id: str,
        thread_ts: str,
        field_name: str,
    ) -> Optional[DraftEdit]:
        """Get the most recent edit for a specific field.

        Useful for conflict detection - compare current with proposed.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp
            field_name: Field to look up

        Returns:
            Most recent DraftEdit for field, or None
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM draft_edits
                WHERE channel_id = %s AND thread_ts = %s AND field_name = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (channel_id, thread_ts, field_name))
            row = await cur.fetchone()
        return self._row_to_model(row) if row else None

    async def get_edit_count(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> int:
        """Get total number of edits for a draft.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp

        Returns:
            Count of edits
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT COUNT(*) FROM draft_edits
                WHERE channel_id = %s AND thread_ts = %s
            """, (channel_id, thread_ts))
            row = await cur.fetchone()
        return row[0] if row else 0

    def _row_to_model(self, row: tuple) -> DraftEdit:
        """Convert database row to DraftEdit model."""
        return DraftEdit(
            edit_id=str(row[0]),
            thread_ts=row[1],
            channel_id=row[2],
            user_id=row[3],
            field_name=row[4],
            old_value=row[5],
            new_value=row[6],
            source_message_ts=row[7],
            edit_type=row[8],
            created_at=row[9],
        )
