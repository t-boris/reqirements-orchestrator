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
    # Structure handlers (Phase 28.6)
    handle_approve_structure,
    handle_edit_structure,
    # Duplicate handling (Phase 11.1)
    handle_link_duplicate,
    handle_add_to_duplicate,
    handle_create_anyway,
    handle_update_existing,
    handle_show_more_duplicates,
    handle_modal_link_duplicate,
    handle_modal_create_anyway,
    # Hint button handling (Phase 12 Onboarding)
    handle_hint_selection,
    # Help example button handling (Phase 12 Onboarding)
    handle_help_example,
    # Channel join handling (Phase 12)
    handle_member_joined_channel,
    # Scope source selection (Fix B)
    handle_scope_source,
    # Review to ticket handling (Phase 13)
    handle_review_to_ticket,
    handle_scope_gate_submit,
    # Architecture approval (Phase 20)
    handle_approve_architecture,
    # Review artifact actions (Phase 25)
    handle_review_approve,
    handle_turn_into_workitem,
    # Decision linking (Phase 21-05)
    handle_link_decision,
    handle_skip_decision_link,
    handle_decision_link_prompt,
    # Decision button handlers (Phase 30)
    register_decision_handlers,
    # Multi-ticket handlers (Phase 22)
    handle_multi_ticket_confirm_quantity,
    handle_multi_ticket_split,
    handle_multi_ticket_edit_story,
    handle_multi_ticket_edit_item,
    handle_multi_ticket_edit_submit,
    handle_multi_ticket_remove_item,
    handle_multi_ticket_approve,
    handle_multi_ticket_cancel,
    handle_multi_ticket_retry_failed,
    handle_multi_ticket_cancel_confirm,
    # Update preview handlers (conversational update flow)
    handle_update_preview_apply,
    handle_update_preview_edit,
    handle_update_preview_cancel,
    handle_update_edit_modal_submit,
    # Draft conflict handlers (Phase 27.3)
    register_draft_conflict_handlers,
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
from src.slack.handlers.change_request import (
    handle_change_request_approve,
    handle_change_request_cancel,
    handle_change_request_edit,
)
from src.slack.handlers.preflight import register_preflight_handlers
from src.slack.handlers.attachments import on_file_shared, register_attachment_handlers
from src.slack.handlers.task_plan import register_task_plan_handlers
from src.slack.handlers.question import register_question_handlers

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

    # File uploads - register attachments for extraction (Phase 34)
    app.event("file_shared")(on_file_shared)

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

    # Structure handlers (Phase 28.6)
    app.action("approve_structure")(handle_approve_structure)
    app.action("edit_structure")(handle_edit_structure)

    # View submission handlers
    app.view("edit_draft_modal")(handle_edit_draft_submit)

    # Action handlers for duplicate handling (Phase 11.1)
    app.action("link_duplicate")(handle_link_duplicate)
    app.action("add_to_duplicate")(handle_add_to_duplicate)
    app.action("create_anyway")(handle_create_anyway)
    app.action("update_existing")(handle_update_existing)
    app.action("show_more_duplicates")(handle_show_more_duplicates)
    # Modal link buttons - pattern matches modal_link_duplicate_PROJ-123
    app.action(re.compile(r"^modal_link_duplicate_.*"))(handle_modal_link_duplicate)
    app.action("modal_create_anyway")(handle_modal_create_anyway)

    # Hint button actions (Phase 12 onboarding)
    app.action(re.compile(r"^hint_select_.*"))(handle_hint_selection)

    # Help example buttons (Phase 12 onboarding)
    app.action(re.compile(r"^help_example_.*"))(handle_help_example)

    # Scope source buttons (Fix B - ask_scope_source action)
    app.action(re.compile(r"^scope_source_.*"))(handle_scope_source)

    # Review to ticket action (Phase 13)
    app.action("review_to_ticket")(handle_review_to_ticket)

    # Architecture approval (Phase 20)
    app.action("approve_architecture")(handle_approve_architecture)

    # Review artifact actions (Phase 25)
    app.action("review_approve")(handle_review_approve)
    app.action("review_to_workitem")(handle_turn_into_workitem)
    # Dismiss is a no-op (ack only)
    app.action("review_dismiss")(lambda ack, body, client: ack())

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

    # Multi-ticket actions (Phase 22)
    app.action("multi_ticket_confirm_quantity")(handle_multi_ticket_confirm_quantity)
    app.action("multi_ticket_split")(handle_multi_ticket_split)
    # Edit item - matches both old (edit_story) and new (edit_item) patterns
    app.action(re.compile(r"^multi_ticket_edit_story:.*"))(handle_multi_ticket_edit_story)
    app.action(re.compile(r"^multi_ticket_edit_item:.*"))(handle_multi_ticket_edit_item)
    # Remove item
    app.action(re.compile(r"^multi_ticket_remove_item:.*"))(handle_multi_ticket_remove_item)
    app.action(re.compile(r"^multi_ticket_approve(?::\d+)?$"))(handle_multi_ticket_approve)
    app.action(re.compile(r"^multi_ticket_cancel(?::\d+)?$"))(handle_multi_ticket_cancel)
    app.action(re.compile(r"^multi_ticket_retry_failed(?::\d+)?$"))(handle_multi_ticket_retry_failed)
    app.action(re.compile(r"^multi_ticket_add_item(?::\d+)?$"))(handle_multi_ticket_approve)  # Add item shows full preview

    # Multi-ticket view submissions (Phase 22)
    app.view("multi_ticket_edit_submit")(handle_multi_ticket_edit_submit)
    app.view("multi_ticket_cancel_confirm")(handle_multi_ticket_cancel_confirm)

    # Update preview actions (conversational update flow)
    app.action(re.compile(r"^update_preview_apply(?::\d+)?$"))(handle_update_preview_apply)
    app.action(re.compile(r"^update_preview_edit(?::\d+)?$"))(handle_update_preview_edit)
    app.action(re.compile(r"^update_preview_cancel(?::\d+)?$"))(handle_update_preview_cancel)
    app.view("update_edit_modal")(handle_update_edit_modal_submit)

    # Change request actions (Phase 25.3)
    app.action("change_request_approve")(handle_change_request_approve)
    app.action("change_request_cancel")(handle_change_request_cancel)
    app.action("change_request_edit")(handle_change_request_edit)

    # Draft conflict actions (Phase 27.3)
    register_draft_conflict_handlers(app)

    # Preflight sync actions (Phase 29.4)
    register_preflight_handlers(app)

    # Decision button handlers (Phase 30)
    register_decision_handlers(app)

    # Attachment pin/unpin handlers (Phase 34)
    register_attachment_handlers(app)

    # TaskPlan button handlers (Phase 35)
    register_task_plan_handlers(app)

    # Question button handlers (Phase 36)
    register_question_handlers(app)

    logger.info("Slack handlers registered: app_mention, message, member_joined_channel, file_shared, /jira, /help, /maro, select_epic_*, dedup, contradiction, draft_approval, edit_modal, duplicate_actions, hint_select, help_example, review_to_ticket, approve_architecture, scope_gate_buttons, create_stories, jira_commands, decision_link, sync, multi_ticket, update_preview, change_request, draft_conflict, preflight, decision_buttons, attachment_pin_unpin, task_plan, question")
