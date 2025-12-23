"""
PostgreSQL Checkpointer - State persistence for LangGraph.

Uses asyncpg to store graph state in PostgreSQL, enabling:
- Conversation continuity across restarts
- Human-in-the-loop resume capability
- Thread-based state isolation
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import asyncpg
import structlog
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from src.config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# SQL Schema
# =============================================================================

CREATE_CHECKPOINTS_TABLE = """
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (thread_id, checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_id
ON langgraph_checkpoints(thread_id);

CREATE INDEX IF NOT EXISTS idx_checkpoints_created_at
ON langgraph_checkpoints(created_at);
"""

CREATE_WRITES_TABLE = """
CREATE TABLE IF NOT EXISTS langgraph_writes (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    value JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (thread_id, checkpoint_id, task_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_writes_thread_checkpoint
ON langgraph_writes(thread_id, checkpoint_id);
"""


# =============================================================================
# PostgreSQL Checkpointer
# =============================================================================


class PostgresCheckpointer(BaseCheckpointSaver):
    """
    Async PostgreSQL checkpointer for LangGraph state persistence.

    Stores checkpoints in PostgreSQL with support for:
    - Thread-based isolation (Slack channel + thread_ts)
    - Checkpoint history for rollback
    - Metadata for debugging
    """

    def __init__(self, pool: asyncpg.Pool):
        """
        Initialize the checkpointer with a connection pool.

        Args:
            pool: Asyncpg connection pool.
        """
        super().__init__()
        self.pool = pool

    async def setup(self) -> None:
        """
        Create required database tables if they don't exist.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(CREATE_CHECKPOINTS_TABLE)
            await conn.execute(CREATE_WRITES_TABLE)
            logger.info("checkpointer_tables_created")

    async def aget_tuple(self, config: dict) -> CheckpointTuple | None:
        """
        Get the latest checkpoint for a thread.

        Args:
            config: Configuration with thread_id.

        Returns:
            CheckpointTuple if found, None otherwise.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")

        async with self.pool.acquire() as conn:
            if checkpoint_id:
                # Get specific checkpoint
                row = await conn.fetchrow(
                    """
                    SELECT checkpoint_id, parent_checkpoint_id, checkpoint, metadata
                    FROM langgraph_checkpoints
                    WHERE thread_id = $1 AND checkpoint_id = $2
                    """,
                    thread_id,
                    checkpoint_id,
                )
            else:
                # Get latest checkpoint
                row = await conn.fetchrow(
                    """
                    SELECT checkpoint_id, parent_checkpoint_id, checkpoint, metadata
                    FROM langgraph_checkpoints
                    WHERE thread_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    thread_id,
                )

            if not row:
                return None

            checkpoint_data = json.loads(row["checkpoint"])
            metadata_data = json.loads(row["metadata"]) if row["metadata"] else {}

            return CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_id": row["checkpoint_id"],
                    }
                },
                checkpoint=checkpoint_data,
                metadata=metadata_data,
                parent_config=(
                    {"configurable": {"thread_id": thread_id, "checkpoint_id": row["parent_checkpoint_id"]}}
                    if row["parent_checkpoint_id"]
                    else None
                ),
                pending_writes=[],
            )

    # Alias for backward compatibility
    async def aget(self, config: dict) -> CheckpointTuple | None:
        """Alias for aget_tuple."""
        return await self.aget_tuple(config)

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict | None = None,
    ) -> dict:
        """
        Save a checkpoint.

        Args:
            config: Configuration with thread_id.
            checkpoint: Checkpoint data to save.
            metadata: Checkpoint metadata.
            new_versions: Channel versions (unused, for API compatibility).

        Returns:
            Updated config with checkpoint_id.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint.get("id") if isinstance(checkpoint, dict) else checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO langgraph_checkpoints
                    (thread_id, checkpoint_id, parent_checkpoint_id, checkpoint, metadata)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (thread_id, checkpoint_id)
                DO UPDATE SET checkpoint = $4, metadata = $5
                """,
                thread_id,
                checkpoint_id,
                parent_checkpoint_id,
                json.dumps(checkpoint),
                json.dumps(metadata),
            )

        logger.debug(
            "checkpoint_saved",
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
        )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: dict,
        writes: list[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """
        Save intermediate writes for a checkpoint.

        Args:
            config: Configuration with thread_id and checkpoint_id.
            writes: List of (channel, value) tuples.
            task_id: Task identifier.
        """
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id", "")

        async with self.pool.acquire() as conn:
            for idx, (channel, value) in enumerate(writes):
                await conn.execute(
                    """
                    INSERT INTO langgraph_writes
                        (thread_id, checkpoint_id, task_id, idx, channel, value)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (thread_id, checkpoint_id, task_id, idx)
                    DO UPDATE SET channel = $5, value = $6
                    """,
                    thread_id,
                    checkpoint_id,
                    task_id,
                    idx,
                    channel,
                    json.dumps(value) if value is not None else None,
                )

    async def alist(
        self,
        config: dict,
        *,
        filter: dict | None = None,
        before: dict | None = None,
        limit: int | None = None,
    ):
        """
        List checkpoints for a thread.

        Args:
            config: Configuration with thread_id.
            filter: Optional metadata filter.
            before: List checkpoints before this config.
            limit: Maximum number of checkpoints to return.

        Yields:
            CheckpointTuple for each matching checkpoint.
        """
        thread_id = config["configurable"]["thread_id"]

        query = """
            SELECT checkpoint_id, parent_checkpoint_id, checkpoint, metadata
            FROM langgraph_checkpoints
            WHERE thread_id = $1
        """
        params = [thread_id]

        if before:
            before_id = before["configurable"].get("checkpoint_id")
            if before_id:
                query += " AND checkpoint_id < $2"
                params.append(before_id)

        query += " ORDER BY created_at DESC"

        if limit:
            query += f" LIMIT {limit}"

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

            for row in rows:
                checkpoint = Checkpoint(**json.loads(row["checkpoint"]))
                metadata = CheckpointMetadata(**json.loads(row["metadata"]))

                yield CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_id": row["checkpoint_id"],
                        }
                    },
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config=(
                        {"configurable": {"thread_id": thread_id, "checkpoint_id": row["parent_checkpoint_id"]}}
                        if row["parent_checkpoint_id"]
                        else None
                    ),
                )

    # Sync methods required by base class (delegate to async)
    def get_tuple(self, config: dict) -> CheckpointTuple | None:
        """Sync wrapper for aget_tuple."""
        return asyncio.get_event_loop().run_until_complete(self.aget_tuple(config))

    def get(self, config: dict) -> CheckpointTuple | None:
        """Sync wrapper for aget."""
        return self.get_tuple(config)

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict | None = None,
    ) -> dict:
        """Sync wrapper for aput."""
        return asyncio.get_event_loop().run_until_complete(
            self.aput(config, checkpoint, metadata, new_versions)
        )

    def put_writes(
        self,
        config: dict,
        writes: list[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Sync wrapper for aput_writes."""
        asyncio.get_event_loop().run_until_complete(
            self.aput_writes(config, writes, task_id)
        )

    def list(
        self,
        config: dict,
        *,
        filter: dict | None = None,
        before: dict | None = None,
        limit: int | None = None,
    ):
        """Sync wrapper for alist - returns list instead of generator."""
        async def _collect():
            results = []
            async for item in self.alist(config, filter=filter, before=before, limit=limit):
                results.append(item)
            return results

        return asyncio.get_event_loop().run_until_complete(_collect())


# =============================================================================
# Connection Pool Management
# =============================================================================

_pool: asyncpg.Pool | None = None
_checkpointer: PostgresCheckpointer | None = None


async def get_pool() -> asyncpg.Pool:
    """
    Get or create the database connection pool.

    Returns:
        Asyncpg connection pool.
    """
    global _pool

    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url.replace("+asyncpg", ""),  # Remove SQLAlchemy prefix
            min_size=2,
            max_size=10,
        )
        logger.info("database_pool_created")

    return _pool


async def get_checkpointer() -> PostgresCheckpointer:
    """
    Get or create the singleton checkpointer instance.

    Returns:
        PostgresCheckpointer instance.
    """
    global _checkpointer

    if _checkpointer is None:
        pool = await get_pool()
        _checkpointer = PostgresCheckpointer(pool)
        await _checkpointer.setup()

    return _checkpointer


async def close_pool() -> None:
    """
    Close the database connection pool.

    Should be called during application shutdown.
    """
    global _pool, _checkpointer

    if _pool is not None:
        await _pool.close()
        _pool = None
        _checkpointer = None
        logger.info("database_pool_closed")


# =============================================================================
# Utility Functions
# =============================================================================


def create_thread_id(channel_id: str, thread_ts: str | None = None) -> str:
    """
    Create a unique thread ID from Slack identifiers.

    Args:
        channel_id: Slack channel ID.
        thread_ts: Slack thread timestamp (optional).

    Returns:
        Unique thread ID for checkpointing.
    """
    if thread_ts:
        return f"{channel_id}:{thread_ts}"
    return f"{channel_id}:main"


async def get_thread_state(thread_id: str) -> dict | None:
    """
    Get the current state for a thread.

    Useful for debugging and status commands.

    Args:
        thread_id: Thread ID to look up.

    Returns:
        Current state dict or None if not found.
    """
    checkpointer = await get_checkpointer()

    config = {"configurable": {"thread_id": thread_id}}
    result = await checkpointer.aget(config)

    if result:
        return result.checkpoint.get("channel_values", {})
    return None


async def clear_thread(thread_id: str) -> bool:
    """
    Clear all checkpoints for a thread.

    Used by /req-clean command.

    Args:
        thread_id: Thread ID to clear.

    Returns:
        True if successful.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM langgraph_checkpoints WHERE thread_id = $1",
            thread_id,
        )
        await conn.execute(
            "DELETE FROM langgraph_writes WHERE thread_id = $1",
            thread_id,
        )

    logger.info("thread_cleared", thread_id=thread_id)
    return True
