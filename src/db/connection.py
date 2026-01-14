"""Async database connection utilities using psycopg v3."""
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from psycopg import AsyncConnection

from src.config import get_settings


# Module-level connection string (used for direct connections)
_conninfo: Optional[str] = None
_initialized: bool = False


async def init_db() -> None:
    """Initialize database connection.

    Call once at application startup. Tests connection and stores conninfo.

    Raises:
        RuntimeError: If already initialized.
        psycopg.OperationalError: If connection to database fails.
    """
    global _conninfo, _initialized
    if _initialized:
        raise RuntimeError("Database already initialized. Call close_db() first.")

    settings = get_settings()
    _conninfo = settings.database_url

    # Test connection
    async with await AsyncConnection.connect(_conninfo) as conn:
        await conn.execute("SELECT 1")

    _initialized = True


async def close_db() -> None:
    """Reset database initialization state.

    Call at application shutdown. Safe to call even if never initialized.
    """
    global _conninfo, _initialized
    _conninfo = None
    _initialized = False


@asynccontextmanager
async def get_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Get a database connection.

    Async context manager that yields a connection.
    Connection is automatically closed when context exits.

    Usage:
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                result = await cur.fetchone()

    Yields:
        AsyncConnection: A database connection.

    Raises:
        RuntimeError: If database not initialized (call init_db() first).
        psycopg.OperationalError: If connection cannot be obtained.
    """
    if not _initialized or _conninfo is None:
        raise RuntimeError(
            "Database not initialized. Call init_db() at application startup."
        )

    async with await AsyncConnection.connect(_conninfo) as conn:
        yield conn
