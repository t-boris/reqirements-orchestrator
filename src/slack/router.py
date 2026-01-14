"""Router that registers all Slack event handlers."""

import logging
import re
from slack_bolt import App

from src.slack.handlers import (
    handle_app_mention,
    handle_message,
    handle_jira_command,
    handle_epic_selection_sync,
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

    # Action handlers for Epic selection buttons
    # Pattern matches: select_epic_PROJ-123, select_epic_new, etc.
    app.action(re.compile(r"^select_epic_.*"))(handle_epic_selection_sync)

    logger.info("Slack handlers registered: app_mention, message, /jira, select_epic_*")
