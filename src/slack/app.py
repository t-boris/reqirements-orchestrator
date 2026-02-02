"""Slack Bolt AsyncApp setup.

Ref: RESEARCH.md Pattern 1 - AsyncApp with FastAPI
"""

import logging

from slack_bolt.async_app import AsyncApp

from src.config import get_settings

logger = logging.getLogger(__name__)

# Global bolt app instance (created lazily)
_bolt_app: AsyncApp | None = None


def create_bolt_app() -> AsyncApp:
    """Create and configure the Bolt AsyncApp.

    Bolt reads SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET from env automatically.
    We also pass them explicitly for clarity.
    """
    settings = get_settings()

    app = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )

    # Register all handlers
    _register_handlers(app)

    logger.info("Bolt AsyncApp created with all handlers registered")
    return app


def _register_handlers(app: AsyncApp) -> None:
    """Register all handlers on the Bolt app."""
    from src.slack.handlers import (
        register_event_handlers,
        register_action_handlers,
        register_command_handlers,
    )

    register_event_handlers(app)
    register_action_handlers(app)
    register_command_handlers(app)


def get_bolt_app() -> AsyncApp:
    """Get or create the global Bolt app instance."""
    global _bolt_app
    if _bolt_app is None:
        _bolt_app = create_bolt_app()
    return _bolt_app
