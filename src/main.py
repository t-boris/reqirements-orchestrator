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
    """Health check endpoint with DB status."""
    health_status = {
        "status": "ok",
        "version": "2.0.0",
        "checks": {
            "database": "unknown",
        },
    }

    # Check database connection
    try:
        settings = get_settings()
        # Build asyncpg connection URL (without the +asyncpg driver prefix)
        db_url = (
            f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_dbname}"
        )
        import asyncpg

        conn = await asyncpg.connect(db_url)
        await conn.execute("SELECT 1")
        await conn.close()
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["checks"]["database"] = f"error: {str(e)}"
        health_status["status"] = "degraded"

    return health_status


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
