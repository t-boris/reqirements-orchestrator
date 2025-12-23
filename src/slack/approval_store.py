"""
Approval Store - PostgreSQL storage for permanent approvals.

Provides persistent storage for "Approve Always" patterns.
"""

from datetime import datetime
from typing import Any

import structlog

from src.graph.checkpointer import get_pool

logger = structlog.get_logger()


# =============================================================================
# SQL Schema
# =============================================================================

CREATE_APPROVALS_TABLE = """
CREATE TABLE IF NOT EXISTS permanent_approvals (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    pattern TEXT NOT NULL,
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(channel_id, pattern)
);

CREATE INDEX IF NOT EXISTS idx_approvals_channel_id
ON permanent_approvals(channel_id);
"""


# =============================================================================
# Database Operations
# =============================================================================


async def init_approval_store() -> None:
    """
    Initialize the approval store tables.

    Should be called during application startup.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(CREATE_APPROVALS_TABLE)
        logger.info("approval_store_initialized")


async def store_permanent_approval(
    channel_id: str,
    pattern: str,
    user_id: str,
) -> int:
    """
    Store a permanent approval in the database.

    Args:
        channel_id: Slack channel ID.
        pattern: Approval pattern (e.g., issue type, keyword).
        user_id: User who created the approval.

    Returns:
        ID of the created approval.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO permanent_approvals (channel_id, pattern, user_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (channel_id, pattern) DO UPDATE
            SET user_id = $3, created_at = NOW()
            RETURNING id
            """,
            channel_id,
            pattern,
            user_id,
        )

        approval_id = row["id"]

        logger.info(
            "permanent_approval_stored",
            id=approval_id,
            channel_id=channel_id,
            pattern=pattern,
        )

        return approval_id


async def get_permanent_approvals(channel_id: str) -> list[dict[str, Any]]:
    """
    Get all permanent approvals for a channel.

    Args:
        channel_id: Slack channel ID.

    Returns:
        List of approval records.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, pattern, user_id, created_at
            FROM permanent_approvals
            WHERE channel_id = $1
            ORDER BY created_at DESC
            """,
            channel_id,
        )

        return [
            {
                "id": row["id"],
                "pattern": row["pattern"],
                "user_id": row["user_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


async def delete_permanent_approval(
    channel_id: str,
    approval_id: int | str,
) -> bool:
    """
    Delete a permanent approval.

    Args:
        channel_id: Slack channel ID.
        approval_id: Approval ID to delete.

    Returns:
        True if deleted, False if not found.
    """
    pool = await get_pool()

    try:
        approval_id_int = int(approval_id)
    except ValueError:
        return False

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM permanent_approvals
            WHERE id = $1 AND channel_id = $2
            """,
            approval_id_int,
            channel_id,
        )

        deleted = result.endswith("1")

        if deleted:
            logger.info(
                "permanent_approval_deleted",
                id=approval_id_int,
                channel_id=channel_id,
            )

        return deleted


async def check_permanent_approval(
    channel_id: str,
    draft: dict[str, Any],
) -> bool:
    """
    Check if a draft matches any permanent approval patterns.

    Args:
        channel_id: Slack channel ID.
        draft: Requirement draft to check.

    Returns:
        True if auto-approved.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pattern FROM permanent_approvals
            WHERE channel_id = $1
            """,
            channel_id,
        )

        if not rows:
            return False

        # Check if any pattern matches
        issue_type = draft.get("issue_type", "").lower()
        title = draft.get("title", "").lower()
        labels = [l.lower() for l in draft.get("labels", [])]

        for row in rows:
            pattern = row["pattern"].lower()

            # Match against issue type
            if pattern == issue_type:
                logger.info(
                    "permanent_approval_matched",
                    channel_id=channel_id,
                    pattern=pattern,
                    match_type="issue_type",
                )
                return True

            # Match against title keywords
            if pattern in title:
                logger.info(
                    "permanent_approval_matched",
                    channel_id=channel_id,
                    pattern=pattern,
                    match_type="title",
                )
                return True

            # Match against labels
            if pattern in labels:
                logger.info(
                    "permanent_approval_matched",
                    channel_id=channel_id,
                    pattern=pattern,
                    match_type="label",
                )
                return True

        return False


async def clear_channel_approvals(channel_id: str) -> int:
    """
    Clear all approvals for a channel.

    Args:
        channel_id: Slack channel ID.

    Returns:
        Number of approvals deleted.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM permanent_approvals
            WHERE channel_id = $1
            """,
            channel_id,
        )

        # Parse "DELETE N" result
        count = int(result.split()[-1]) if result else 0

        logger.info(
            "channel_approvals_cleared",
            channel_id=channel_id,
            count=count,
        )

        return count
