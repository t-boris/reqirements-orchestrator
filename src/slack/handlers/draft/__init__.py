"""Draft handlers package.

Handles the ticket draft lifecycle: creation, transformation, and approval.

Re-exports all handlers for backward compatibility.
"""

from src.slack.handlers.draft.create import (
    check_preflight_for_create,
    build_create_preflight_blocks,
    build_ticket_announcement_blocks,
)

from src.slack.handlers.draft.transform import (
    handle_reject_draft,
    handle_edit_draft_submit,
    handle_edit_structure,
)

from src.slack.handlers.draft.approve import (
    handle_approve_draft,
    handle_approve_structure,
)

# Legacy aliases for backward compatibility
_check_preflight_for_create = check_preflight_for_create
_build_create_preflight_blocks = build_create_preflight_blocks
_build_ticket_announcement_blocks = build_ticket_announcement_blocks

# Expose handle_draft_approval as an alias for consistency with plan verification
handle_draft_approval = handle_approve_draft

__all__ = [
    # Create module
    "check_preflight_for_create",
    "build_create_preflight_blocks",
    "build_ticket_announcement_blocks",
    # Legacy aliases
    "_check_preflight_for_create",
    "_build_create_preflight_blocks",
    "_build_ticket_announcement_blocks",
    # Transform module
    "handle_reject_draft",
    "handle_edit_draft_submit",
    "handle_edit_structure",
    # Approve module
    "handle_approve_draft",
    "handle_approve_structure",
    "handle_draft_approval",
]
