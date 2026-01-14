"""Database module for async PostgreSQL connectivity.

Provides async database connection utilities using psycopg v3.

Usage:
    from src.db import get_connection, init_db, close_db

    # At application startup
    await init_db()

    # During request handling
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")

    # At application shutdown
    await close_db()
"""
from src.db.connection import close_db, get_connection, init_db

__all__ = ["get_connection", "init_db", "close_db"]
