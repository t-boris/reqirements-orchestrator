"""Database pool management for asyncpg."""

import logging

import asyncpg

from src.config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the global asyncpg connection pool."""
    global _pool
    if _pool is None:
        settings = get_settings()
        dsn = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_dbname}"
        )
        _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
        logger.info("Database pool created")
    return _pool


async def close_pool() -> None:
    """Close the database pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
