"""Router that registers all Slack event handlers."""

import logging
import re
from slack_bolt import App

from src.slack.handlers import (
    handle_app_mention,
    handle_message,
    handle_jira_command,
    handle_help_command,
    handle_maro_command,
    handle_epic_selection_sync,
    handle_merge_context,
    handle_ignore_dedup,
    handle_contradiction_conflict,
    handle_contradiction_override,
    handle_contradiction_both,
    handle_approve_draft,
    handle_reject_draft,
    handle_edit_draft_submit,
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

    # Slash commands
    app.command("/jira")(handle_jira_command)
    app.command("/help")(handle_help_command)
    app.command("/maro")(handle_maro_command)

    # Action handlers for Epic selection buttons
    # Pattern matches: select_epic_PROJ-123, select_epic_new, etc.
    app.action(re.compile(r"^select_epic_.*"))(handle_epic_selection_sync)

    # Action handlers for dedup suggestions
    app.action("merge_thread_context")(handle_merge_context)
    app.action("ignore_dedup_suggestion")(handle_ignore_dedup)

    # Action handlers for contradiction resolution
    app.action("resolve_contradiction_conflict")(handle_contradiction_conflict)
    app.action("resolve_contradiction_override")(handle_contradiction_override)
    app.action("resolve_contradiction_both")(handle_contradiction_both)

    # Action handlers for draft approval/rejection
    app.action("approve_draft")(handle_approve_draft)
    app.action("reject_draft")(handle_reject_draft)

    # View submission handlers
    app.view("edit_draft_modal")(handle_edit_draft_submit)

    logger.info("Slack handlers registered: app_mention, message, /jira, /help, /maro, select_epic_*, dedup, contradiction, draft_approval, edit_modal")
