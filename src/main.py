"""
MARO v2 - Requirements Engineering Bot

Main entry point for the FastAPI application with Slack Socket Mode.
"""

import structlog
import uvicorn

from src.config.settings import get_settings
from src.slack.bot import create_fastapi_app

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()
settings = get_settings()

# Create FastAPI application
app = create_fastapi_app()


@app.on_event("startup")
async def startup_event():
    """
    Initialize services on startup.
    """
    logger.info(
        "maro_starting",
        version="2.0.0",
        environment=settings.environment,
    )

    # Initialize approval store
    from src.slack.approval_store import init_approval_store

    await init_approval_store()

    # Load personas
    from src.personas import load_personas

    await load_personas()

    logger.info("maro_started")


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.environment == "development",
        log_level="info",
    )
