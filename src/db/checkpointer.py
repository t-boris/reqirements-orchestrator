"""LangGraph PostgreSQL checkpointer for agent state persistence.

Provides PostgresSaver configuration for resumable agent sessions.
Uses langgraph-checkpoint-postgres which requires psycopg v3 sync connections.

Usage:
    from src.db import get_checkpointer, setup_checkpointer

    # Once at startup: create checkpointer tables
    setup_checkpointer()

    # When compiling graph: pass checkpointer
    checkpointer = get_checkpointer()
    graph = workflow.compile(checkpointer=checkpointer)
"""
from langgraph.checkpoint.postgres import PostgresSaver

from src.config import get_settings


def get_checkpointer() -> PostgresSaver:
    """Get a configured PostgresSaver checkpointer.

    Creates a new PostgresSaver instance using the database connection string
    from settings. The checkpointer persists LangGraph state to PostgreSQL,
    enabling resumable agent sessions.

    Note: PostgresSaver uses psycopg v3 sync connections internally.
    Each call creates a new connection. For high-throughput scenarios,
    consider caching the checkpointer instance.

    Returns:
        PostgresSaver: Configured checkpointer for LangGraph state persistence.
    """
    settings = get_settings()
    return PostgresSaver.from_conn_string(settings.database_url)


def setup_checkpointer() -> None:
    """Initialize checkpointer database tables.

    Call once at application startup or during database migrations.
    Creates the necessary tables for LangGraph state persistence.

    This is idempotent - safe to call multiple times.
    """
    checkpointer = get_checkpointer()
    checkpointer.setup()
