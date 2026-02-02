"""MARO 2.0 - Main entry point.

Starts FastAPI server with Slack Bolt integration.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes.slack import router as slack_router
from src.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler.

    Startup and shutdown events.
    """
    # Startup
    settings = get_settings()
    logger.info("MARO 2.0 starting...")
    logger.info(f"Environment: {settings.environment}")

    # Initialize Bolt app (this registers handlers)
    from src.slack.app import get_bolt_app

    get_bolt_app()
    logger.info("Slack Bolt app initialized")

    yield

    # Shutdown
    logger.info("MARO 2.0 shutting down...")


# Create FastAPI app
app = FastAPI(
    title="MARO 2.0",
    description="Multi-Agent Requirements Orchestrator - Slack bot for transforming conversations into work items",
    version="2.0.0",
    lifespan=lifespan,
)

# Mount Slack routes
app.include_router(slack_router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "2.0.0"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "MARO 2.0",
        "description": "Threads propose. Channels decide. Jira executes.",
        "slack_events": "/slack/events",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=3000,
        reload=settings.environment == "development",
    )
