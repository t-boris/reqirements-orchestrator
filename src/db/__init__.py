"""Database module for PostgreSQL connectivity and LangGraph state persistence.

Provides async database connection utilities using psycopg v3 and
LangGraph checkpointer for agent state persistence.

Usage:
    from src.db import get_connection, init_db, close_db, get_checkpointer, setup_checkpointer

    # At application startup
    await init_db()
    setup_checkpointer()  # Initialize checkpointer tables

    # During request handling
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")

    # For LangGraph graph compilation
    checkpointer = get_checkpointer()
    graph = workflow.compile(checkpointer=checkpointer)

    # At application shutdown
    await close_db()
"""
from src.db.checkpointer import get_checkpointer, setup_checkpointer
from src.db.connection import close_db, get_connection, init_db

__all__ = ["get_connection", "init_db", "close_db", "get_checkpointer", "setup_checkpointer"]
