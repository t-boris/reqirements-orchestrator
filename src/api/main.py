"""
FastAPI Application - Main entry point.

Provides REST API for the web dashboard and external integrations.
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import graphs, channels, health
from src.config.settings import get_settings
from src.adapters.persistence.database import init_database
from src.adapters.slack.bot import SlackBot
from src.adapters.slack.handlers import SlackHandlers
from src.adapters.slack.formatter import SlackFormatter
from src.adapters.slack.config import ChannelConfig
from src.core.agents.orchestrator import AgentOrchestrator
from src.core.services.graph_service import GraphService
from src.core.services.summarization_service import SummarizationService
from src.core.events.store import EventStore
from src.adapters.llm.factory import create_summarization_client

logger = structlog.get_logger()

# Global references for cleanup
_slack_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Initializes and cleans up resources on startup/shutdown.
    """
    global _slack_task

    settings = get_settings()

    # Initialize database
    logger.info("initializing_database")
    database = await init_database(settings)

    # Initialize services
    logger.info("initializing_services")
    event_store = EventStore()
    graph_service = GraphService(event_store=event_store)
    llm_client = create_summarization_client(settings)
    summarization_service = SummarizationService(
        llm_client=llm_client,
        context_threshold_percent=settings.context_threshold_percent,
    )
    channel_config = ChannelConfig()

    # Initialize agent orchestrator
    orchestrator = AgentOrchestrator(
        graph_service=graph_service,
        summarization_service=summarization_service,
        settings=settings,
        channel_config=channel_config,
    )

    # Initialize Slack components
    formatter = SlackFormatter(dashboard_url=f"http://localhost:{settings.port}")
    handlers = SlackHandlers(
        orchestrator=orchestrator,
        graph_service=graph_service,
        channel_config=channel_config,
        formatter=formatter,
    )
    slack_bot = SlackBot(settings=settings, handlers=handlers)

    # Start Slack bot in background
    logger.info("starting_slack_bot")
    _slack_task = asyncio.create_task(slack_bot.start_socket_mode())

    yield

    # Cleanup
    logger.info("shutting_down")
    if _slack_task:
        _slack_task.cancel()
        try:
            await _slack_task
        except asyncio.CancelledError:
            pass
    await database.close()


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app.
    """
    settings = get_settings()

    app = FastAPI(
        title="MARO - Multi-Agent Requirements Orchestrator",
        description="REST API for the MARO web dashboard",
        version="1.0.0",
        lifespan=lifespan,
        debug=settings.debug,
    )

    # CORS middleware for dashboard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure properly for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(graphs.router, prefix="/api/graphs", tags=["Graphs"])
    app.include_router(channels.router, prefix="/api/channels", tags=["Channels"])

    return app


# Application instance
app = create_app()
