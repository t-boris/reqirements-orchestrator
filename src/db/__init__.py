"""Database module for PostgreSQL connectivity and LangGraph state persistence.

Provides async database connection utilities using psycopg v3,
LangGraph checkpointer for agent state persistence, and session storage
for thread-to-ticket mapping.

Usage:
    from src.db import get_connection, init_db, close_db, get_checkpointer, setup_checkpointer
    from src.db import ThreadSession, ChannelContext, SessionStore

    # At application startup
    await init_db()
    setup_checkpointer()  # Initialize checkpointer tables

    # During request handling
    async with get_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")

    # Session management
    async with get_connection() as conn:
        store = SessionStore(conn)
        await store.create_tables()
        session = await store.get_or_create_session(channel_id, thread_ts, user_id)

    # For LangGraph graph compilation
    checkpointer = get_checkpointer()
    graph = workflow.compile(checkpointer=checkpointer)

    # At application shutdown
    await close_db()
"""
from src.db.checkpointer import get_checkpointer, setup_checkpointer
from src.db.connection import close_db, get_connection, init_db
from src.db.models import ChannelContext, ThreadSession
from src.db.session_store import SessionStore

__all__ = [
    # Connection (02-01)
    "get_connection",
    "init_db",
    "close_db",
    # Checkpointer (02-02)
    "get_checkpointer",
    "setup_checkpointer",
    # Models (02-03)
    "ThreadSession",
    "ChannelContext",
    # Session Store (02-03)
    "SessionStore",
]
