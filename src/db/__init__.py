"""Database module for PostgreSQL connectivity and LangGraph state persistence.

Provides async database connection utilities using psycopg v3,
LangGraph checkpointer for agent state persistence, session storage
for thread-to-ticket mapping, and approval records for idempotency.

Usage:
    from src.db import get_connection, init_db, close_db, get_checkpointer, setup_checkpointer
    from src.db import ThreadSession, ChannelContext, SessionStore
    from src.db import ApprovalStore, ApprovalRecord

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

    # Approval records
    async with get_connection() as conn:
        approval_store = ApprovalStore(conn)
        await approval_store.create_tables()
        is_new = await approval_store.record_approval(session_id, draft_hash, user_id)

    # For LangGraph graph compilation
    checkpointer = get_checkpointer()
    graph = workflow.compile(checkpointer=checkpointer)

    # At application shutdown
    await close_db()
"""
from src.db.checkpointer import get_checkpointer, setup_checkpointer
from src.db.connection import close_db, get_connection, init_db
from src.db.models import (
    ChannelActivitySnapshot,
    ChannelConfig,
    ChannelContext,
    ChannelKnowledge,
    ChannelListeningState,
    RootIndex,
    ThreadSession,
)
from src.db.session_store import SessionStore
from src.db.approval_store import ApprovalStore, ApprovalRecord
from src.db.jira_operations import JiraOperationStore, JiraOperationRecord
from src.db.channel_context_store import ChannelContextStore
from src.db.root_index_store import RootIndexStore
from src.db.listening_store import ListeningStore
from src.db.event_store import EventStore, make_button_event_id
from src.db.fact_store import FactStore, compute_canonical_id
from src.db.board_store import BoardStore, BoardState

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
    "ChannelConfig",
    "ChannelKnowledge",
    "ChannelActivitySnapshot",
    "RootIndex",
    # Session Store (02-03)
    "SessionStore",
    # Approval Store (06-02)
    "ApprovalStore",
    "ApprovalRecord",
    # Jira Operations (07-02)
    "JiraOperationStore",
    "JiraOperationRecord",
    # Channel Context Store (08-01)
    "ChannelContextStore",
    # Root Index Store (08-03)
    "RootIndexStore",
    # Listening Store (11-02)
    "ListeningStore",
    "ChannelListeningState",
    # Event Store (20-02)
    "EventStore",
    "make_button_event_id",
    # Fact Store (20-11)
    "FactStore",
    "compute_canonical_id",
    # Board Store (21-02)
    "BoardStore",
    "BoardState",
]
