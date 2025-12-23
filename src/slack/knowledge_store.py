"""
Knowledge Store - PostgreSQL storage for persona knowledge files.

Provides persistent storage for custom knowledge files uploaded per channel/persona.
"""

from datetime import datetime
from typing import Any

import structlog

from src.graph.checkpointer import get_pool

logger = structlog.get_logger()


# =============================================================================
# SQL Schema
# =============================================================================

CREATE_KNOWLEDGE_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS persona_knowledge_files (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    persona_name TEXT NOT NULL,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(channel_id, persona_name, filename)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_channel_persona
ON persona_knowledge_files(channel_id, persona_name);
"""


# =============================================================================
# Database Operations
# =============================================================================


async def init_knowledge_store() -> None:
    """
    Initialize the knowledge store tables.

    Should be called during application startup.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(CREATE_KNOWLEDGE_FILES_TABLE)
        logger.info("knowledge_store_initialized")


async def save_knowledge_file(
    channel_id: str,
    persona_name: str,
    filename: str,
    content: str,
    uploaded_by: str,
) -> int:
    """
    Save a knowledge file for a persona in a channel.

    Args:
        channel_id: Slack channel ID.
        persona_name: Name of the persona (e.g., "architect").
        filename: Name of the uploaded file.
        content: Text content of the file.
        uploaded_by: User ID who uploaded the file.

    Returns:
        ID of the created/updated file record.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO persona_knowledge_files
                (channel_id, persona_name, filename, content, uploaded_by)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (channel_id, persona_name, filename) DO UPDATE SET
                content = $4,
                uploaded_by = $5,
                created_at = NOW()
            RETURNING id
            """,
            channel_id,
            persona_name,
            filename,
            content,
            uploaded_by,
        )

        file_id = row["id"]

        logger.info(
            "knowledge_file_saved",
            id=file_id,
            channel_id=channel_id,
            persona=persona_name,
            filename=filename,
        )

        return file_id


async def get_knowledge_files(
    channel_id: str,
    persona_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get knowledge files for a channel, optionally filtered by persona.

    Args:
        channel_id: Slack channel ID.
        persona_name: Optional persona filter.

    Returns:
        List of file records with metadata.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        if persona_name:
            rows = await conn.fetch(
                """
                SELECT id, persona_name, filename, content, uploaded_by, created_at
                FROM persona_knowledge_files
                WHERE channel_id = $1 AND persona_name = $2
                ORDER BY created_at DESC
                """,
                channel_id,
                persona_name,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, persona_name, filename, content, uploaded_by, created_at
                FROM persona_knowledge_files
                WHERE channel_id = $1
                ORDER BY persona_name, created_at DESC
                """,
                channel_id,
            )

        return [
            {
                "id": row["id"],
                "persona_name": row["persona_name"],
                "filename": row["filename"],
                "content": row["content"],
                "uploaded_by": row["uploaded_by"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


async def get_knowledge_file(file_id: int) -> dict[str, Any] | None:
    """
    Get a single knowledge file by ID.

    Args:
        file_id: File record ID.

    Returns:
        File record or None if not found.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, channel_id, persona_name, filename, content, uploaded_by, created_at
            FROM persona_knowledge_files
            WHERE id = $1
            """,
            file_id,
        )

        if row:
            return {
                "id": row["id"],
                "channel_id": row["channel_id"],
                "persona_name": row["persona_name"],
                "filename": row["filename"],
                "content": row["content"],
                "uploaded_by": row["uploaded_by"],
                "created_at": row["created_at"],
            }

        return None


async def delete_knowledge_file(
    channel_id: str,
    file_id: int,
) -> bool:
    """
    Delete a knowledge file.

    Args:
        channel_id: Slack channel ID (for access control).
        file_id: File record ID.

    Returns:
        True if deleted, False if not found.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM persona_knowledge_files
            WHERE id = $1 AND channel_id = $2
            """,
            file_id,
            channel_id,
        )

        deleted = result.endswith("1")

        if deleted:
            logger.info(
                "knowledge_file_deleted",
                id=file_id,
                channel_id=channel_id,
            )

        return deleted


async def clear_channel_knowledge(channel_id: str) -> int:
    """
    Clear all knowledge files for a channel.

    Args:
        channel_id: Slack channel ID.

    Returns:
        Number of files deleted.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM persona_knowledge_files
            WHERE channel_id = $1
            """,
            channel_id,
        )

        # Parse "DELETE N" result
        count = int(result.split()[-1]) if result else 0

        logger.info(
            "channel_knowledge_cleared",
            channel_id=channel_id,
            count=count,
        )

        return count


async def get_combined_knowledge(
    channel_id: str,
    persona_name: str,
) -> str:
    """
    Get combined knowledge text for a persona in a channel.

    Combines all uploaded files into a single text block.

    Args:
        channel_id: Slack channel ID.
        persona_name: Persona name.

    Returns:
        Combined knowledge text, or empty string if none.
    """
    files = await get_knowledge_files(channel_id, persona_name)

    if not files:
        return ""

    parts = []
    for file in files:
        parts.append(f"## {file['filename']}\n\n{file['content']}")

    return "\n\n---\n\n".join(parts)
