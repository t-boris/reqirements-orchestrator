"""Slack event and action handlers.

This package contains all Slack handlers split by responsibility:
- core: App mention, background loop, conversation context
- dispatch: Result dispatch, content extraction
- draft: Draft approval, rejection, editing
- duplicates: Duplicate handling actions
- commands: /maro, /persona, /jira, /help commands
- onboarding: Channel join, hints, help examples
- review: Review-to-ticket, scope gate
- misc: Epic selection, contradictions, message events

All handlers are re-exported here for backward compatibility.
"""

# Core handlers
from src.slack.handlers.core import (
    handle_app_mention,
    _run_async,
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
    handle_persona_command,
)

# Draft handlers
from src.slack.handlers.draft import (
    handle_approve_draft,
    handle_reject_draft,
    handle_edit_draft_submit,
)

# Duplicate handlers
from src.slack.handlers.duplicates import (
    handle_link_duplicate,
    handle_add_to_duplicate,
    handle_create_anyway,
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
)

__all__ = [
    # Core
    "handle_app_mention",
    "_run_async",
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
    "handle_persona_command",
    # Draft
    "handle_approve_draft",
    "handle_reject_draft",
    "handle_edit_draft_submit",
    # Duplicates
    "handle_link_duplicate",
    "handle_add_to_duplicate",
    "handle_create_anyway",
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
]
