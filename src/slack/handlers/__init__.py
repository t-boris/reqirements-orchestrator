"""Slack event and action handlers.

This package contains all Slack handlers split by responsibility:
- core: App mention, background loop, conversation context
- dispatch: Result dispatch, content extraction
- draft: Draft approval, rejection, editing
- duplicates: Duplicate handling actions
- commands: /maro, /jira, /help commands
- onboarding: Channel join, hints, help examples
- review: Review-to-ticket, scope gate
- misc: Epic selection, contradictions, message events

All handlers are re-exported here for backward compatibility.
"""

# Core handlers
from src.slack.handlers.core import (
    handle_app_mention,
    _run_async,
    _capture_user_metadata,
)

# Message and thread handlers
from src.slack.handlers.misc import (
    handle_message,
    handle_epic_selection_sync,
    handle_contradiction_conflict,
    handle_contradiction_override,
    handle_contradiction_both,
)

# Command handlers
from src.slack.handlers.commands import (
    handle_jira_command,
    handle_help_command,
    handle_maro_command,
)

# Draft handlers
from src.slack.handlers.draft import (
    handle_approve_draft,
    handle_reject_draft,
    handle_edit_draft_submit,
    # Structure handlers (Phase 28.6)
    handle_approve_structure,
    handle_edit_structure,
)

# Duplicate handlers
from src.slack.handlers.duplicates import (
    handle_link_duplicate,
    handle_add_to_duplicate,
    handle_create_anyway,
    handle_update_existing,
    handle_show_more_duplicates,
    handle_modal_link_duplicate,
    handle_modal_create_anyway,
    handle_merge_context,
    handle_ignore_dedup,
)

# Onboarding handlers
from src.slack.handlers.onboarding import (
    handle_hint_selection,
    handle_help_example,
    handle_member_joined_channel,
)

# Review handlers
from src.slack.handlers.review import (
    handle_review_to_ticket,
    handle_scope_gate_submit,
    handle_approve_architecture,
    # Artifact handlers (Phase 25)
    handle_review_approve,
    handle_turn_into_workitem,
)

# Scope gate handlers (AMBIGUOUS intent)
from src.slack.handlers.scope_gate import (
    handle_scope_gate_review,
    handle_scope_gate_ticket,
    handle_scope_gate_dismiss,
)

# Story creation handlers
from src.slack.handlers.stories import (
    handle_create_stories_confirm,
    handle_create_stories_cancel,
)

# Jira command handlers (Phase 21)
from src.slack.handlers.jira_commands import (
    handle_jira_command_execute,
    handle_jira_command_cancel,
    handle_jira_command_select,
    handle_jira_command_confirm,
    handle_jira_command_ambiguous,
)

# Decision linking handlers (Phase 21-05)
from src.slack.handlers.decision_link import (
    handle_link_decision,
    handle_skip_decision_link,
    handle_decision_link_prompt,
)

# Sync handlers (Phase 21-04)
from src.slack.handlers.sync import (
    handle_sync_apply_all,
    handle_sync_use_slack,
    handle_sync_use_jira,
    handle_sync_skip,
    handle_sync_cancel,
    handle_sync_merge,
    handle_sync_merge_submit,
)

# Multi-ticket handlers (Phase 22)
from src.slack.handlers.multi_ticket import (
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
)

# Update preview handlers (conversational update flow)
from src.slack.handlers.update import (
    handle_update_preview_apply,
    handle_update_preview_edit,
    handle_update_preview_cancel,
    handle_update_edit_modal_submit,
)

# Commit approval handlers (Phase 23.3)
from src.slack.handlers.commit import register_commit_handlers

# Jira sync handlers (Phase 23.4)
from src.slack.handlers.jira_sync import register_jira_sync_handlers

# Change request handlers (Phase 25.3)
from src.slack.handlers.change_request import (
    handle_change_request_approve,
    handle_change_request_cancel,
    handle_change_request_edit,
)

# Draft conflict handlers (Phase 27.3)
from src.slack.handlers.draft_conflict import (
    handle_draft_conflict_resolve_existing,
    handle_draft_conflict_resolve_proposed,
    register_draft_conflict_handlers,
)

# Preflight sync handlers (Phase 29.4)
from src.slack.handlers.preflight import (
    handle_preflight_proceed,
    handle_preflight_pull_only,
    handle_preflight_use_jira,
    handle_preflight_use_channel,
    handle_preflight_cancel,
    handle_preflight_link_existing,
    register_preflight_handlers,
)

# Decision button handlers (Phase 30)
from src.slack.handlers.decision_buttons import (
    register_decision_handlers,
)

# Question handlers (Phase 36)
from src.slack.handlers.question import (
    register_question_handlers,
)

__all__ = [
    # Core
    "handle_app_mention",
    "_run_async",
    "_capture_user_metadata",
    # Misc
    "handle_message",
    "handle_epic_selection_sync",
    "handle_contradiction_conflict",
    "handle_contradiction_override",
    "handle_contradiction_both",
    # Commands
    "handle_jira_command",
    "handle_help_command",
    "handle_maro_command",
    # Draft
    "handle_approve_draft",
    "handle_reject_draft",
    "handle_edit_draft_submit",
    # Structure handlers (Phase 28.6)
    "handle_approve_structure",
    "handle_edit_structure",
    # Duplicates
    "handle_link_duplicate",
    "handle_add_to_duplicate",
    "handle_create_anyway",
    "handle_update_existing",
    "handle_show_more_duplicates",
    "handle_modal_link_duplicate",
    "handle_modal_create_anyway",
    "handle_merge_context",
    "handle_ignore_dedup",
    # Onboarding
    "handle_hint_selection",
    "handle_help_example",
    "handle_member_joined_channel",
    # Review
    "handle_review_to_ticket",
    "handle_scope_gate_submit",
    "handle_approve_architecture",
    # Artifact handlers (Phase 25)
    "handle_review_approve",
    "handle_turn_into_workitem",
    # Scope Gate (AMBIGUOUS intent)
    "handle_scope_gate_review",
    "handle_scope_gate_ticket",
    "handle_scope_gate_dismiss",
    # Story creation
    "handle_create_stories_confirm",
    "handle_create_stories_cancel",
    # Jira commands (Phase 21)
    "handle_jira_command_execute",
    "handle_jira_command_cancel",
    "handle_jira_command_select",
    "handle_jira_command_confirm",
    "handle_jira_command_ambiguous",
    # Decision linking (Phase 21-05)
    "handle_link_decision",
    "handle_skip_decision_link",
    "handle_decision_link_prompt",
    # Sync handlers (Phase 21-04)
    "handle_sync_apply_all",
    "handle_sync_use_slack",
    "handle_sync_use_jira",
    "handle_sync_skip",
    "handle_sync_cancel",
    "handle_sync_merge",
    "handle_sync_merge_submit",
    # Multi-ticket handlers (Phase 22)
    "handle_multi_ticket_confirm_quantity",
    "handle_multi_ticket_split",
    "handle_multi_ticket_edit_story",
    "handle_multi_ticket_edit_item",
    "handle_multi_ticket_edit_submit",
    "handle_multi_ticket_remove_item",
    "handle_multi_ticket_approve",
    "handle_multi_ticket_cancel",
    "handle_multi_ticket_retry_failed",
    "handle_multi_ticket_cancel_confirm",
    # Update preview handlers (conversational update flow)
    "handle_update_preview_apply",
    "handle_update_preview_edit",
    "handle_update_preview_cancel",
    "handle_update_edit_modal_submit",
    # Commit approval handlers (Phase 23.3)
    "register_commit_handlers",
    # Jira sync handlers (Phase 23.4)
    "register_jira_sync_handlers",
    # Change request handlers (Phase 25.3)
    "handle_change_request_approve",
    "handle_change_request_cancel",
    "handle_change_request_edit",
    # Draft conflict handlers (Phase 27.3)
    "handle_draft_conflict_resolve_existing",
    "handle_draft_conflict_resolve_proposed",
    "register_draft_conflict_handlers",
    # Preflight sync handlers (Phase 29.4)
    "handle_preflight_proceed",
    "handle_preflight_pull_only",
    "handle_preflight_use_jira",
    "handle_preflight_use_channel",
    "handle_preflight_cancel",
    "handle_preflight_link_existing",
    "register_preflight_handlers",
    # Decision button handlers (Phase 30)
    "register_decision_handlers",
    # Question handlers (Phase 36)
    "register_question_handlers",
]
