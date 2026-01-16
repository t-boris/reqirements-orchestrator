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
    # Duplicate handling (Phase 11.1)
    handle_link_duplicate,
    handle_add_to_duplicate,
    handle_create_anyway,
    handle_show_more_duplicates,
    handle_modal_link_duplicate,
    handle_modal_create_anyway,
    # Hint button handling (Phase 12 Onboarding)
    handle_hint_selection,
    # Help example button handling (Phase 12 Onboarding)
    handle_help_example,
    # Channel join handling (Phase 12)
    handle_member_joined_channel,
    # Review to ticket handling (Phase 13)
    handle_review_to_ticket,
    handle_scope_gate_submit,
    # Architecture approval (Phase 20)
    handle_approve_architecture,
    # Decision linking (Phase 21-05)
    handle_link_decision,
    handle_skip_decision_link,
    handle_decision_link_prompt,
)
from src.slack.handlers.scope_gate import (
    handle_scope_gate_review,
    handle_scope_gate_ticket,
    handle_scope_gate_dismiss,
)
from src.slack.handlers.stories import (
    handle_create_stories_confirm,
    handle_create_stories_cancel,
)
from src.slack.handlers.jira_commands import (
    handle_jira_command_execute,
    handle_jira_command_cancel,
    handle_jira_command_select,
)
from src.slack.handlers.sync import (
    handle_sync_apply_all,
    handle_sync_use_slack,
    handle_sync_use_jira,
    handle_sync_skip,
    handle_sync_cancel,
    handle_sync_merge,
    handle_sync_merge_submit,
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

    # Channel join - post pinned quick-reference (Phase 12)
    app.event("member_joined_channel")(handle_member_joined_channel)

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

    # Action handlers for duplicate handling (Phase 11.1)
    app.action("link_duplicate")(handle_link_duplicate)
    app.action("add_to_duplicate")(handle_add_to_duplicate)
    app.action("create_anyway")(handle_create_anyway)
    app.action("show_more_duplicates")(handle_show_more_duplicates)
    # Modal link buttons - pattern matches modal_link_duplicate_PROJ-123
    app.action(re.compile(r"^modal_link_duplicate_.*"))(handle_modal_link_duplicate)
    app.action("modal_create_anyway")(handle_modal_create_anyway)

    # Hint button actions (Phase 12 onboarding)
    app.action(re.compile(r"^hint_select_.*"))(handle_hint_selection)

    # Help example buttons (Phase 12 onboarding)
    app.action(re.compile(r"^help_example_.*"))(handle_help_example)

    # Review to ticket action (Phase 13)
    app.action("review_to_ticket")(handle_review_to_ticket)

    # Architecture approval (Phase 20)
    app.action("approve_architecture")(handle_approve_architecture)

    # Scope gate modal submission (Phase 13)
    app.view("review_scope_gate")(handle_scope_gate_submit)

    # Scope gate button actions (Phase 20)
    app.action("scope_gate_review")(handle_scope_gate_review)
    app.action("scope_gate_ticket")(handle_scope_gate_ticket)
    app.action("scope_gate_dismiss")(handle_scope_gate_dismiss)

    # Story creation actions
    app.action("create_stories_confirm")(handle_create_stories_confirm)
    app.action("create_stories_cancel")(handle_create_stories_cancel)

    # Jira command actions (Phase 21)
    app.action("jira_command_execute")(handle_jira_command_execute)
    app.action("jira_command_cancel")(handle_jira_command_cancel)
    # Pattern matches: jira_command_select_PROJ-123
    app.action(re.compile(r"^jira_command_select_.*"))(handle_jira_command_select)

    # Decision linking actions (Phase 21-05)
    # Pattern matches: link_decision_PROJ-123
    app.action(re.compile(r"^link_decision_.*"))(handle_link_decision)
    app.action("skip_decision_link")(handle_skip_decision_link)
    app.action("decision_link_prompt")(handle_decision_link_prompt)

    # Sync actions (Phase 21-04)
    app.action("sync_apply_all")(handle_sync_apply_all)
    app.action("sync_cancel")(handle_sync_cancel)
    app.action("sync_merge")(handle_sync_merge)
    # Sync merge modal submission
    app.view("sync_merge_modal")(handle_sync_merge_submit)
    # Pattern matches: sync_use_slack_*, sync_use_jira_*, sync_skip_*
    app.action(re.compile(r"^sync_use_slack.*"))(handle_sync_use_slack)
    app.action(re.compile(r"^sync_use_jira.*"))(handle_sync_use_jira)
    app.action(re.compile(r"^sync_skip.*"))(handle_sync_skip)

    logger.info("Slack handlers registered: app_mention, message, member_joined_channel, /jira, /help, /maro, select_epic_*, dedup, contradiction, draft_approval, edit_modal, duplicate_actions, hint_select, help_example, review_to_ticket, approve_architecture, scope_gate_buttons, create_stories, jira_commands, decision_link, sync")
