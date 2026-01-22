"""Main entry point for the MARO Slack bot."""

import asyncio
import logging
import sys

from src.config import get_settings
from src.db.checkpointer import setup_checkpointer
from src.db.connection import init_db, get_connection
from src.db.session_store import SessionStore
from src.db.channel_context_store import ChannelContextStore
from src.db.listening_store import ListeningStore
from src.db.workitem_store import WorkItemStore
from src.db.channel_mode_store import ChannelModeStore
from src.db.commit_store import CommitStore
from src.db.jira_operations import JiraOperationStore
from src.db.debug_store import DebugStore
from src.db.artifact_store import ArtifactStore
from src.health import start_health_server
from src.slack.app import get_slack_app, start_socket_mode
from src.slack.router import register_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def init_database() -> None:
    """Initialize database connection pool, tables, and checkpointer."""
    logger.info("Initializing database...")
    await init_db()
    await setup_checkpointer()

    # Create application tables
    async with get_connection() as conn:
        # Legacy session store (deprecated, kept for migration)
        session_store = SessionStore(conn)
        await session_store.create_tables()

        # Phase 23: Communication as Source of Truth
        workitem_store = WorkItemStore(conn)
        await workitem_store.create_tables()

        channel_mode_store = ChannelModeStore(conn)
        await channel_mode_store.create_tables()

        commit_store = CommitStore(conn)
        await commit_store.create_tables()

        # Existing stores
        context_store = ChannelContextStore(conn)
        await context_store.create_tables()

        listening_store = ListeningStore(conn)
        await listening_store.create_tables()

        # Jira operations tracking
        jira_ops_store = JiraOperationStore(conn)
        await jira_ops_store.create_tables()

        # Debug mode tracking (Phase 24)
        debug_store = DebugStore(conn)
        await debug_store.create_tables()

        # Review artifact persistence (Phase 25)
        artifact_store = ArtifactStore(conn)
        await artifact_store.create_tables()

    logger.info("Database initialized")


def main() -> None:
    """Main entry point."""
    logger.info("Starting MARO bot...")

    # Validate settings early
    settings = get_settings()
    logger.info("Settings loaded")

    # Initialize database
    asyncio.run(init_database())

    # Start health server for Docker healthcheck
    start_health_server(port=8000)

    # Initialize Slack app and register handlers
    app = get_slack_app()
    register_handlers(app)

    logger.info("MARO bot ready")

    # Start Socket Mode (blocking)
    start_socket_mode()


if __name__ == "__main__":
    main()
