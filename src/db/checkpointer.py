"""LangGraph PostgreSQL checkpointer for agent state persistence.

Provides PostgresSaver configuration for resumable agent sessions.
Uses langgraph-checkpoint-postgres which requires psycopg v3 sync connections.

Usage:
    from src.db import get_checkpointer, setup_checkpointer

    # Once at startup: create checkpointer tables
    setup_checkpointer()

    # When compiling graph: pass checkpointer instance
    checkpointer = get_checkpointer()
    graph = workflow.compile(checkpointer=checkpointer)
"""
import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from langgraph.checkpoint.postgres import PostgresSaver

from src.config import get_settings

logger = logging.getLogger(__name__)

# Module-level singleton checkpointer for long-running app
_checkpointer: Optional[PostgresSaver] = None
_checkpointer_cm = None  # Keep context manager alive


def get_checkpointer() -> PostgresSaver:
    """Get the singleton PostgresSaver checkpointer instance.

    Creates a persistent checkpointer on first call that stays alive
    for the lifetime of the application. This is required for long-running
    apps like Slack bots.

    Returns:
        PostgresSaver: Configured checkpointer for LangGraph state persistence.
    """
    global _checkpointer, _checkpointer_cm

    if _checkpointer is None:
        settings = get_settings()
        # Create context manager and enter it - keep both alive
        _checkpointer_cm = PostgresSaver.from_conn_string(settings.database_url)
        _checkpointer = _checkpointer_cm.__enter__()
        logger.info("PostgresSaver checkpointer initialized")

    return _checkpointer


@contextmanager
def get_checkpointer_cm() -> Iterator[PostgresSaver]:
    """Get a checkpointer as context manager (for short-lived operations).

    Use this for one-off operations like setup. For graph compilation,
    use get_checkpointer() instead.

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
    with get_checkpointer_cm() as checkpointer:
        checkpointer.setup()
