"""LangGraph PostgreSQL checkpointer for agent state persistence.

Provides AsyncPostgresSaver configuration for resumable agent sessions.
Uses langgraph-checkpoint-postgres with psycopg v3 async connections.

Usage:
    from src.db import get_checkpointer, setup_checkpointer

    # Once at startup: create checkpointer tables
    await setup_checkpointer()

    # When compiling graph: pass checkpointer instance
    checkpointer = await get_checkpointer()
    graph = workflow.compile(checkpointer=checkpointer)
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.config import get_settings

logger = logging.getLogger(__name__)

# Module-level singleton checkpointer for long-running app
_checkpointer: Optional[AsyncPostgresSaver] = None
_checkpointer_cm = None  # Keep context manager alive
_lock = asyncio.Lock()


async def get_checkpointer() -> AsyncPostgresSaver:
    """Get the singleton AsyncPostgresSaver checkpointer instance.

    Creates a persistent checkpointer on first call that stays alive
    for the lifetime of the application. This is required for long-running
    apps like Slack bots using async graph streaming.

    Returns:
        AsyncPostgresSaver: Configured checkpointer for LangGraph state persistence.
    """
    global _checkpointer, _checkpointer_cm

    if _checkpointer is None:
        async with _lock:
            # Double-check after acquiring lock
            if _checkpointer is None:
                settings = get_settings()
                # Create async context manager and enter it - keep both alive
                _checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.database_url)
                _checkpointer = await _checkpointer_cm.__aenter__()
                logger.info("AsyncPostgresSaver checkpointer initialized")

    return _checkpointer


@asynccontextmanager
async def get_checkpointer_cm() -> AsyncIterator[AsyncPostgresSaver]:
    """Get a checkpointer as async context manager (for short-lived operations).

    Use this for one-off operations like setup. For graph compilation,
    use get_checkpointer() instead.

    Yields:
        AsyncPostgresSaver: Configured checkpointer for LangGraph state persistence.
    """
    settings = get_settings()
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        yield checkpointer


async def setup_checkpointer() -> None:
    """Initialize checkpointer database tables.

    Call once at application startup or during database migrations.
    Creates the necessary tables for LangGraph state persistence.

    This is idempotent - safe to call multiple times.
    """
    async with get_checkpointer_cm() as checkpointer:
        await checkpointer.setup()
