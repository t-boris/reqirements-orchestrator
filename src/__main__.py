"""Main entry point for the MARO Slack bot."""

import asyncio
import logging
import sys

from src.config import get_settings
from src.db.checkpointer import setup_checkpointer
from src.db.connection import init_db
from src.health import start_health_server
from src.slack.app import get_slack_app, start_socket_mode
from src.slack.router import register_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def init_database() -> None:
    """Initialize database connection pool and run checkpointer setup."""
    logger.info("Initializing database...")
    await init_db()
    await setup_checkpointer()
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
