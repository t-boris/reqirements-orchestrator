"""AttachmentStore with async CRUD operations using psycopg v3.

Store for file attachments. Supports:
- Create/update attachment records
- Query by channel, thread, or file_id
- Pin/unpin for context control
- Status lifecycle management

Table: attachments
Indexes: channel_id, thread_ts, file_id (unique), status
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from psycopg import AsyncConnection

from src.schemas.attachment import Attachment, AttachmentStatus


class AttachmentStore:
    """Store for attachment records.

    Usage:
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            attachment = await store.create(
                file_id="F123ABC",
                filename="spec.pdf",
                mimetype="application/pdf",
                channel_id="C123",
                uploaded_by="U456",
            )
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create attachments table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS attachments (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT,

                    -- Slack file identity
                    file_id TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    mimetype TEXT NOT NULL,
                    size_bytes INTEGER,

                    -- Extracted content
                    extracted_text TEXT,
                    summary TEXT,
                    token_count INTEGER,

                    -- Lifecycle
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,

                    -- Context control
                    pinned BOOLEAN NOT NULL DEFAULT FALSE,
                    pinned_by TEXT,
                    pinned_at TIMESTAMPTZ,

                    -- Metadata
                    uploaded_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Index for channel queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_attachments_channel
                ON attachments(channel_id)
            """)

            # Index for thread queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_attachments_thread
                ON attachments(channel_id, thread_ts)
                WHERE thread_ts IS NOT NULL
            """)

            # Index for status queries (find pending for processing)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_attachments_status
                ON attachments(status)
                WHERE status IN ('pending', 'extracting')
            """)

            # Index for pinned queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_attachments_pinned
                ON attachments(channel_id, pinned)
                WHERE pinned = TRUE
            """)

            await self._conn.commit()

    async def create(
        self,
        file_id: str,
        filename: str,
        mimetype: str,
        channel_id: str,
        uploaded_by: str,
        thread_ts: Optional[str] = None,
        size_bytes: Optional[int] = None,
    ) -> Attachment:
        """Create a new attachment record.

        Returns existing attachment if file_id already exists.
        """
        attachment_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            # Use ON CONFLICT to handle duplicate file_id
            await cur.execute(
                """
                INSERT INTO attachments (
                    id, channel_id, thread_ts, file_id, filename,
                    mimetype, size_bytes, uploaded_by, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_id) DO UPDATE
                SET updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                (
                    str(attachment_id), channel_id, thread_ts, file_id,
                    filename, mimetype, size_bytes, uploaded_by, now, now,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_attachment(row)

    async def get(self, attachment_id: UUID) -> Optional[Attachment]:
        """Get attachment by ID."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM attachments WHERE id = %s",
                (str(attachment_id),),
            )
            row = await cur.fetchone()

        return self._row_to_attachment(row) if row else None

    async def get_by_file_id(self, file_id: str) -> Optional[Attachment]:
        """Get attachment by Slack file ID."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM attachments WHERE file_id = %s",
                (file_id,),
            )
            row = await cur.fetchone()

        return self._row_to_attachment(row) if row else None

    async def list_by_channel(
        self,
        channel_id: str,
        thread_ts: Optional[str] = None,
        status: Optional[AttachmentStatus] = None,
        pinned_only: bool = False,
        limit: int = 50,
    ) -> list[Attachment]:
        """List attachments in a channel, optionally filtered."""
        conditions = ["channel_id = %s"]
        params: list = [channel_id]

        if thread_ts is not None:
            conditions.append("thread_ts = %s")
            params.append(thread_ts)

        if status is not None:
            conditions.append("status = %s")
            params.append(status.value)

        if pinned_only:
            conditions.append("pinned = TRUE")

        params.append(limit)

        query = f"""
            SELECT * FROM attachments
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT %s
        """

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_attachment(row) for row in rows]

    async def get_pending(self, limit: int = 10) -> list[Attachment]:
        """Get attachments pending extraction."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM attachments
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (limit,),
            )
            rows = await cur.fetchall()

        return [self._row_to_attachment(row) for row in rows]

    async def update_status(
        self,
        attachment_id: UUID,
        status: AttachmentStatus,
        error_message: Optional[str] = None,
    ) -> bool:
        """Update attachment status."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE attachments
                SET status = %s, error_message = %s, updated_at = %s
                WHERE id = %s
                RETURNING id
                """,
                (status.value, error_message, now, str(attachment_id)),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    async def set_extracted_content(
        self,
        attachment_id: UUID,
        extracted_text: str,
        summary: Optional[str] = None,
        token_count: Optional[int] = None,
    ) -> bool:
        """Set extracted text and mark as ready."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE attachments
                SET extracted_text = %s,
                    summary = %s,
                    token_count = %s,
                    status = 'ready',
                    updated_at = %s
                WHERE id = %s
                RETURNING id
                """,
                (extracted_text, summary, token_count, now, str(attachment_id)),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    async def pin(
        self,
        attachment_id: UUID,
        pinned_by: str,
    ) -> bool:
        """Pin attachment to context."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE attachments
                SET pinned = TRUE, pinned_by = %s, pinned_at = %s, updated_at = %s
                WHERE id = %s
                RETURNING id
                """,
                (pinned_by, now, now, str(attachment_id)),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    async def unpin(self, attachment_id: UUID) -> bool:
        """Unpin attachment from context."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE attachments
                SET pinned = FALSE, pinned_by = NULL, pinned_at = NULL, updated_at = %s
                WHERE id = %s
                RETURNING id
                """,
                (now, str(attachment_id)),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return row is not None

    def _row_to_attachment(self, row: tuple) -> Attachment:
        """Convert database row to Attachment model.

        Row order (18 columns):
        0: id, 1: channel_id, 2: thread_ts, 3: file_id, 4: filename,
        5: mimetype, 6: size_bytes, 7: extracted_text, 8: summary,
        9: token_count, 10: status, 11: error_message, 12: pinned,
        13: pinned_by, 14: pinned_at, 15: uploaded_by, 16: created_at,
        17: updated_at
        """
        return Attachment(
            id=UUID(str(row[0])),
            channel_id=row[1],
            thread_ts=row[2],
            file_id=row[3],
            filename=row[4],
            mimetype=row[5],
            size_bytes=row[6],
            extracted_text=row[7],
            summary=row[8],
            token_count=row[9],
            status=AttachmentStatus(row[10]),
            error_message=row[11],
            pinned=row[12],
            pinned_by=row[13],
            pinned_at=row[14],
            uploaded_by=row[15],
            created_at=row[16],
            updated_at=row[17],
        )
