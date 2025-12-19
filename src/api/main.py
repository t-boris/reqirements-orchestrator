"""
FastAPI Application - Main entry point.

Provides REST API for the web dashboard and external integrations.
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import graphs, channels, health
from src.config.settings import get_settings
from src.adapters.persistence.database import init_database

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Initializes and cleans up resources on startup/shutdown.
    """
    settings = get_settings()

    # Initialize database
    logger.info("initializing_database")
    database = await init_database(settings)

    yield

    # Cleanup
    logger.info("shutting_down")
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
