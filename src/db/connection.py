"""Async database connection utilities using psycopg v3."""
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from src.config import get_settings


# Module-level connection pool (initialized at startup)
_pool: Optional[AsyncConnectionPool] = None


async def init_db() -> None:
    """Initialize the database connection pool.

    Call once at application startup. Creates an async connection pool
    using the database_url from settings.

    Raises:
        RuntimeError: If pool is already initialized.
        psycopg.OperationalError: If connection to database fails.
    """
    global _pool
    if _pool is not None:
        raise RuntimeError("Database pool already initialized. Call close_db() first.")

    settings = get_settings()
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        open=False,  # Don't open immediately, we'll do it explicitly
    )
    await _pool.open()


async def close_db() -> None:
    """Close the database connection pool.

    Call at application shutdown. Closes all connections in the pool.
    Safe to call even if pool was never initialized.
    """
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Get a database connection from the pool.

    Async context manager that yields a connection from the pool.
    Connection is automatically returned to pool when context exits.

    Usage:
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                result = await cur.fetchone()

    Yields:
        AsyncConnection: A database connection from the pool.

    Raises:
        RuntimeError: If database pool not initialized (call init_db() first).
        psycopg.OperationalError: If connection cannot be obtained.
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialized. Call init_db() at application startup."
        )

    async with _pool.connection() as conn:
        yield conn
