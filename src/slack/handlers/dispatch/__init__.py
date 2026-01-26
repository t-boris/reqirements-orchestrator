"""Dispatch package - result dispatching and content extraction logic.

INVARIANT I1: SuperMode = sole UI contract
All user-facing messages use super_mode, never intent.
Intent is internal routing detail only.

This package handles dispatching graph results to appropriate skills and
extracting content for ticket updates and comments.

Re-exports all public functions from submodules for backward compatibility.
"""

# Core dispatch functions
from src.slack.handlers.dispatch.core import (
    _dispatch_result,
    resolve_attachment_context,
    _extract_update_content,
    _extract_comment_content,
    _check_preflight_for_action,
    # Review handlers
    _handle_review_continuation,
    _handle_review,
    # Ticket action handlers
    _handle_ticket_action,
    _handle_create_stories,
    # Sync and search handlers
    _handle_sync_request,
    _handle_jira_search,
    _handle_change_request_preview,
    # OPS handler
    _handle_ops_response,
    # TaskPlan handlers
    _handle_task_plan_created,
    _handle_task_confirmation,
    _handle_task_plan_complete,
    _handle_task_plan_blocked,
    _handle_task_failed,
    _handle_task_rejected,
    # Question engine handlers
    _handle_question_posted,
    _handle_budget_exhausted,
    _post_question_ui,
    _post_budget_exhausted_ui,
    # Constants
    UPDATE_EXTRACTION_PROMPT,
    COMMENT_EXTRACTION_PROMPT,
    STORY_GENERATION_PROMPT,
)

# Draft handlers
from src.slack.handlers.dispatch.draft import (
    _handle_draft_conflict,
    _handle_transform_applied,
)

# Decision handlers
from src.slack.handlers.dispatch.decision import (
    _handle_decision_approval,
    _link_decision_to_jira,
    _prompt_decision_link,
    _handle_expand_decision,
    DECISION_EXTRACTION_PROMPT,
)

# Public API aliases (without underscore prefix)
dispatch_result = _dispatch_result

__all__ = [
    # Main dispatch function
    "dispatch_result",
    "_dispatch_result",
    # Core utilities
    "resolve_attachment_context",
    "_extract_update_content",
    "_extract_comment_content",
    "_check_preflight_for_action",
    # Review handlers
    "_handle_review_continuation",
    "_handle_review",
    # Ticket handlers
    "_handle_ticket_action",
    "_handle_create_stories",
    # Sync/search handlers
    "_handle_sync_request",
    "_handle_jira_search",
    "_handle_change_request_preview",
    # OPS handler
    "_handle_ops_response",
    # TaskPlan handlers
    "_handle_task_plan_created",
    "_handle_task_confirmation",
    "_handle_task_plan_complete",
    "_handle_task_plan_blocked",
    "_handle_task_failed",
    "_handle_task_rejected",
    # Question handlers
    "_handle_question_posted",
    "_handle_budget_exhausted",
    "_post_question_ui",
    "_post_budget_exhausted_ui",
    # Draft handlers
    "_handle_draft_conflict",
    "_handle_transform_applied",
    # Decision handlers
    "_handle_decision_approval",
    "_link_decision_to_jira",
    "_prompt_decision_link",
    "_handle_expand_decision",
    # Constants
    "UPDATE_EXTRACTION_PROMPT",
    "COMMENT_EXTRACTION_PROMPT",
    "STORY_GENERATION_PROMPT",
    "DECISION_EXTRACTION_PROMPT",
]
