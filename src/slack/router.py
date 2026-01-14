"""Router that registers all Slack event handlers."""

import logging
from slack_bolt import App

from src.slack.handlers import (
    handle_app_mention,
    handle_message,
    handle_jira_command,
)

logger = logging.getLogger(__name__)


def register_handlers(app: App) -> None:
    """Register all event handlers with the Slack app.

    Call this after get_slack_app() but before start_socket_mode().
    """
    # App mentions - explicit trigger
    app.event("app_mention")(handle_app_mention)

    # Messages - only processes in-thread replies
    app.event("message")(handle_message)

    # Slash command
    app.command("/jira")(handle_jira_command)

    logger.info("Slack handlers registered: app_mention, message, /jira")
