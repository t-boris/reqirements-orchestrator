"""Slack event and action handlers.

This package provides backward compatibility during the handlers split refactoring.
Re-exports all handlers from the original src/slack/handlers.py module.
"""

import importlib.util
import os

# Load the original handlers.py directly to avoid circular import issues
_handlers_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "handlers.py")
_spec = importlib.util.spec_from_file_location("_handlers_impl", _handlers_path)
_handlers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_handlers)

# Re-export all handlers for backward compatibility
handle_app_mention = _handlers.handle_app_mention
handle_message = _handlers.handle_message
handle_jira_command = _handlers.handle_jira_command
handle_help_command = _handlers.handle_help_command
handle_maro_command = _handlers.handle_maro_command
handle_epic_selection_sync = _handlers.handle_epic_selection_sync
handle_merge_context = _handlers.handle_merge_context
handle_ignore_dedup = _handlers.handle_ignore_dedup
handle_contradiction_conflict = _handlers.handle_contradiction_conflict
handle_contradiction_override = _handlers.handle_contradiction_override
handle_contradiction_both = _handlers.handle_contradiction_both
handle_approve_draft = _handlers.handle_approve_draft
handle_reject_draft = _handlers.handle_reject_draft
handle_edit_draft_submit = _handlers.handle_edit_draft_submit
handle_link_duplicate = _handlers.handle_link_duplicate
handle_add_to_duplicate = _handlers.handle_add_to_duplicate
handle_create_anyway = _handlers.handle_create_anyway
handle_show_more_duplicates = _handlers.handle_show_more_duplicates
handle_modal_link_duplicate = _handlers.handle_modal_link_duplicate
handle_modal_create_anyway = _handlers.handle_modal_create_anyway
handle_hint_selection = _handlers.handle_hint_selection
handle_help_example = _handlers.handle_help_example
handle_member_joined_channel = _handlers.handle_member_joined_channel
handle_review_to_ticket = _handlers.handle_review_to_ticket
handle_scope_gate_submit = _handlers.handle_scope_gate_submit
_run_async = _handlers._run_async

__all__ = [
    "handle_app_mention",
    "handle_message",
    "handle_jira_command",
    "handle_help_command",
    "handle_maro_command",
    "handle_epic_selection_sync",
    "handle_merge_context",
    "handle_ignore_dedup",
    "handle_contradiction_conflict",
    "handle_contradiction_override",
    "handle_contradiction_both",
    "handle_approve_draft",
    "handle_reject_draft",
    "handle_edit_draft_submit",
    "handle_link_duplicate",
    "handle_add_to_duplicate",
    "handle_create_anyway",
    "handle_show_more_duplicates",
    "handle_modal_link_duplicate",
    "handle_modal_create_anyway",
    "handle_hint_selection",
    "handle_help_example",
    "handle_member_joined_channel",
    "handle_review_to_ticket",
    "handle_scope_gate_submit",
    "_run_async",
]
