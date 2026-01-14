"""LangGraph PostgreSQL checkpointer for agent state persistence.

Provides PostgresSaver configuration for resumable agent sessions.
Uses langgraph-checkpoint-postgres which requires psycopg v3 sync connections.

Usage:
    from src.db import get_checkpointer, setup_checkpointer

    # Once at startup: create checkpointer tables
    setup_checkpointer()

    # When compiling graph: pass checkpointer context manager
    checkpointer_cm = get_checkpointer()
    # Use as context manager in graph operations
"""
from contextlib import contextmanager
from typing import Iterator

from langgraph.checkpoint.postgres import PostgresSaver

from src.config import get_settings


@contextmanager
def get_checkpointer() -> Iterator[PostgresSaver]:
    """Get a configured PostgresSaver checkpointer as context manager.

    Creates a new PostgresSaver instance using the database connection string
    from settings. The checkpointer persists LangGraph state to PostgreSQL,
    enabling resumable agent sessions.

    Note: PostgresSaver uses psycopg v3 sync connections internally.
    Must be used as a context manager.

    Yields:
        PostgresSaver: Configured checkpointer for LangGraph state persistence.
    """
    settings = get_settings()
    with PostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        yield checkpointer


def setup_checkpointer() -> None:
    """Initialize checkpointer database tables.

    Call once at application startup or during database migrations.
    Creates the necessary tables for LangGraph state persistence.

    This is idempotent - safe to call multiple times.
    """
    with get_checkpointer() as checkpointer:
        checkpointer.setup()
