"""
Slack Bot - Main Slack Bolt application with Socket Mode.

Initializes the async Slack app with all handlers and integrates with FastAPI.
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from src.config.settings import get_settings
from src.slack.handlers import register_handlers

logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# Slack App Initialization
# =============================================================================

# Initialize Slack Bolt async app
app = AsyncApp(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
)


# Register all message and command handlers
register_handlers(app)


# Socket mode handler for WebSocket connection
socket_handler: AsyncSocketModeHandler | None = None


async def start_socket_mode() -> None:
    """
    Start the Socket Mode handler.

    Socket Mode creates an outbound WebSocket connection to Slack,
    eliminating the need for a public IP or webhook endpoint.
    """
    global socket_handler

    if not settings.slack_app_token:
        logger.error("slack_app_token_missing")
        raise ValueError("SLACK_APP_TOKEN is required for Socket Mode")

    socket_handler = AsyncSocketModeHandler(
        app=app,
        app_token=settings.slack_app_token,
    )

    logger.info("starting_socket_mode")
    await socket_handler.start_async()


async def stop_socket_mode() -> None:
    """
    Stop the Socket Mode handler gracefully.
    """
    global socket_handler

    if socket_handler:
        logger.info("stopping_socket_mode")
        await socket_handler.close_async()
        socket_handler = None


# =============================================================================
# FastAPI Integration
# =============================================================================


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    """
    FastAPI lifespan context manager.

    Initializes stores and starts Socket Mode on startup, cleans up on shutdown.
    """
    # Startup
    logger.info("application_starting")

    # Initialize database stores
    from src.slack.approval_store import init_approval_store
    from src.slack.channel_config_store import init_channel_config_store
    from src.slack.knowledge_store import init_knowledge_store
    from src.personas import load_personas

    await init_approval_store()
    logger.info("approval_store_initialized")

    await init_channel_config_store()
    logger.info("channel_config_store_initialized")

    await init_knowledge_store()
    logger.info("knowledge_store_initialized")

    await load_personas()
    logger.info("personas_loaded")

    # Start Socket Mode in background
    socket_task = asyncio.create_task(start_socket_mode())

    try:
        yield
    finally:
        # Shutdown
        logger.info("application_shutting_down")

        # Stop Socket Mode
        await stop_socket_mode()

        # Close database connections
        from src.graph.checkpointer import close_pool

        await close_pool()

        # Cancel socket task if still running
        if not socket_task.done():
            socket_task.cancel()
            try:
                await socket_task
            except asyncio.CancelledError:
                pass


def create_fastapi_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app instance.
    """
    fastapi_app = FastAPI(
        title="MARO v2 - Requirements Bot",
        description="Slack bot for requirements engineering with Jira integration",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Register admin routes for Zep and LangGraph debugging
    from src.admin.routes import router as admin_router
    fastapi_app.include_router(admin_router)

    @fastapi_app.get("/health")
    async def health_check():
        """Health check endpoint for monitoring."""
        return {
            "status": "healthy",
            "version": "2.0.0",
        }

    @fastapi_app.get("/ready")
    async def readiness_check():
        """Readiness check for Kubernetes/Docker."""
        # Check if Socket Mode is connected
        is_connected = socket_handler is not None and socket_handler.client is not None

        return {
            "ready": is_connected,
            "socket_mode": "connected" if is_connected else "disconnected",
        }

    return fastapi_app


# =============================================================================
# Utility Functions
# =============================================================================


async def send_message(
    channel: str,
    text: str,
    thread_ts: str | None = None,
    blocks: list | None = None,
) -> dict:
    """
    Send a message to a Slack channel.

    Args:
        channel: Channel ID.
        text: Message text (fallback for notifications).
        thread_ts: Thread timestamp for replies.
        blocks: Block Kit blocks for rich formatting.

    Returns:
        Slack API response.
    """
    return await app.client.chat_postMessage(
        channel=channel,
        text=text,
        thread_ts=thread_ts,
        blocks=blocks,
    )


async def update_message(
    channel: str,
    ts: str,
    text: str,
    blocks: list | None = None,
) -> dict:
    """
    Update an existing message.

    Args:
        channel: Channel ID.
        ts: Message timestamp to update.
        text: New message text.
        blocks: New Block Kit blocks.

    Returns:
        Slack API response.
    """
    return await app.client.chat_update(
        channel=channel,
        ts=ts,
        text=text,
        blocks=blocks,
    )


async def add_reaction(
    channel: str,
    timestamp: str,
    name: str,
) -> dict:
    """
    Add a reaction to a message.

    Args:
        channel: Channel ID.
        timestamp: Message timestamp.
        name: Reaction emoji name (without colons).

    Returns:
        Slack API response.
    """
    return await app.client.reactions_add(
        channel=channel,
        timestamp=timestamp,
        name=name,
    )
