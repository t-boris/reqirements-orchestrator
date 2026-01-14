"""Slack Bolt application with Socket Mode."""

import logging
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from src.config import get_settings

logger = logging.getLogger(__name__)

_app: App | None = None
_handler: SocketModeHandler | None = None


def get_slack_app() -> App:
    """Get or create the Slack Bolt app singleton."""
    global _app
    if _app is None:
        settings = get_settings()
        _app = App(
            token=settings.slack_bot_token,
            signing_secret=settings.slack_signing_secret,
        )
        logger.info("Slack app initialized")
    return _app


def start_socket_mode():
    """Start Socket Mode handler (blocking)."""
    global _handler
    settings = get_settings()
    app = get_slack_app()

    _handler = SocketModeHandler(app, settings.slack_app_token)
    logger.info("Starting Socket Mode...")
    _handler.start()


def stop_socket_mode():
    """Stop Socket Mode handler."""
    global _handler
    if _handler:
        _handler.close()
        _handler = None
        logger.info("Socket Mode stopped")
