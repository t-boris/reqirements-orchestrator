"""AttachmentChunkStore with full-text search.

Stores document chunks and enables retrieval via PostgreSQL tsvector.

Table: attachment_chunks
Features: Full-text search, chunk ordering, attachment linkage
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from psycopg import AsyncConnection

from src.schemas.attachment import Attachment


class AttachmentChunk:
    """Chunk of an attachment."""

    def __init__(
        self,
        id: UUID,
        attachment_id: UUID,
        chunk_index: int,
        chunk_text: str,
        token_count: int,
        start_char: int,
        end_char: int,
        created_at: datetime,
    ):
        self.id = id
        self.attachment_id = attachment_id
        self.chunk_index = chunk_index
        self.chunk_text = chunk_text
        self.token_count = token_count
        self.start_char = start_char
        self.end_char = end_char
        self.created_at = created_at


class AttachmentChunkStore:
    """Store for attachment chunks with full-text search.

    Usage:
        async with get_connection() as conn:
            store = AttachmentChunkStore(conn)
            chunks = await store.search(attachment_id, "requirements")
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create attachment_chunks table with search index."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS attachment_chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    attachment_id UUID NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    token_count INTEGER,
                    start_char INTEGER,
                    end_char INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                    -- Full-text search column (auto-generated)
                    search_vector tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', chunk_text)
                    ) STORED,

                    UNIQUE(attachment_id, chunk_index)
                )
            """)

            # Index for attachment queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_attachment
                ON attachment_chunks(attachment_id)
            """)

            # Full-text search index
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_search
                ON attachment_chunks USING GIN(search_vector)
            """)

            await self._conn.commit()

    async def store_chunks(
        self,
        attachment_id: UUID,
        chunks: list[dict],
    ) -> int:
        """Store chunks for an attachment.

        Replaces existing chunks if any.

        Args:
            attachment_id: UUID of the attachment.
            chunks: List of chunk dicts from chunker.

        Returns:
            Number of chunks stored.
        """
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            # Delete existing chunks
            await cur.execute(
                "DELETE FROM attachment_chunks WHERE attachment_id = %s",
                (str(attachment_id),),
            )

            # Insert new chunks
            for chunk in chunks:
                chunk_id = uuid.uuid4()
                await cur.execute(
                    """
                    INSERT INTO attachment_chunks (
                        id, attachment_id, chunk_index, chunk_text,
                        token_count, start_char, end_char, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(chunk_id),
                        str(attachment_id),
                        chunk["chunk_index"],
                        chunk["chunk_text"],
                        chunk.get("token_count"),
                        chunk.get("start_char"),
                        chunk.get("end_char"),
                        now,
                    ),
                )

            await self._conn.commit()

        return len(chunks)

    async def get_chunks(
        self,
        attachment_id: UUID,
        limit: Optional[int] = None,
    ) -> list[AttachmentChunk]:
        """Get all chunks for an attachment in order."""
        query = """
            SELECT id, attachment_id, chunk_index, chunk_text,
                   token_count, start_char, end_char, created_at
            FROM attachment_chunks
            WHERE attachment_id = %s
            ORDER BY chunk_index ASC
        """
        params = [str(attachment_id)]

        if limit:
            query += " LIMIT %s"
            params.append(limit)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_chunk(row) for row in rows]

    async def search(
        self,
        attachment_id: UUID,
        query: str,
        limit: int = 5,
    ) -> list[AttachmentChunk]:
        """Search chunks by content using full-text search.

        Args:
            attachment_id: UUID of the attachment.
            query: Search query text.
            limit: Maximum chunks to return.

        Returns:
            Chunks ranked by relevance.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, attachment_id, chunk_index, chunk_text,
                       token_count, start_char, end_char, created_at,
                       ts_rank(search_vector, plainto_tsquery('english', %s)) as rank
                FROM attachment_chunks
                WHERE attachment_id = %s
                  AND search_vector @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                (query, str(attachment_id), query, limit),
            )
            rows = await cur.fetchall()

        # Row has rank at index 8, ignore it for model
        return [self._row_to_chunk(row[:8]) for row in rows]

    async def search_across_attachments(
        self,
        attachment_ids: list[UUID],
        query: str,
        limit: int = 10,
    ) -> list[tuple[AttachmentChunk, float]]:
        """Search across multiple attachments.

        Returns chunks with relevance scores.

        Args:
            attachment_ids: List of attachment UUIDs.
            query: Search query text.
            limit: Maximum chunks to return.

        Returns:
            List of (chunk, score) tuples.
        """
        if not attachment_ids:
            return []

        placeholders = ",".join(["%s"] * len(attachment_ids))
        params = [query] + [str(aid) for aid in attachment_ids] + [query, limit]

        async with self._conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT id, attachment_id, chunk_index, chunk_text,
                       token_count, start_char, end_char, created_at,
                       ts_rank(search_vector, plainto_tsquery('english', %s)) as rank
                FROM attachment_chunks
                WHERE attachment_id IN ({placeholders})
                  AND search_vector @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                params,
            )
            rows = await cur.fetchall()

        return [
            (self._row_to_chunk(row[:8]), row[8])
            for row in rows
        ]

    async def delete_for_attachment(self, attachment_id: UUID) -> int:
        """Delete all chunks for an attachment."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM attachment_chunks
                WHERE attachment_id = %s
                RETURNING id
                """,
                (str(attachment_id),),
            )
            rows = await cur.fetchall()
            await self._conn.commit()

        return len(rows)

    def _row_to_chunk(self, row: tuple) -> AttachmentChunk:
        """Convert database row to AttachmentChunk."""
        return AttachmentChunk(
            id=UUID(str(row[0])),
            attachment_id=UUID(str(row[1])),
            chunk_index=row[2],
            chunk_text=row[3],
            token_count=row[4],
            start_char=row[5],
            end_char=row[6],
            created_at=row[7],
        )
