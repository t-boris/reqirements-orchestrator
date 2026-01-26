"""Multi-ticket workflow handlers package.

This package handles the multi-ticket creation workflow including:
- Quantity confirmation and batch splitting
- Item editing via modals
- Batch creation with progress tracking
- Cancel and retry operations

All public functions are re-exported here for backward compatibility
with existing imports from `src.slack.handlers.multi_ticket`.
"""

# Creation flow handlers
from src.slack.handlers.multi_ticket.creation import (
    handle_multi_ticket_confirm_quantity,
    handle_multi_ticket_split,
    handle_multi_ticket_approve,
    handle_multi_ticket_retry_failed,
)

# UI and editing handlers
from src.slack.handlers.multi_ticket.ui import (
    handle_multi_ticket_edit_item,
    handle_multi_ticket_edit_story,  # Backward compatibility alias
    handle_multi_ticket_edit_submit,
    handle_multi_ticket_remove_item,
)

# Cancel handlers
from src.slack.handlers.multi_ticket.cancel import (
    handle_multi_ticket_cancel,
    handle_multi_ticket_cancel_confirm,
)

# Linking utilities (for internal use and backward compatibility)
from src.slack.handlers.multi_ticket.linking import (
    extract_item_id,
    extract_story_id,  # Backward compatibility alias
    extract_ui_version,
    # Private function aliases for backward compatibility
    _extract_item_id,
    _extract_story_id,
    _extract_ui_version,
)

__all__ = [
    # Creation flow
    "handle_multi_ticket_confirm_quantity",
    "handle_multi_ticket_split",
    "handle_multi_ticket_approve",
    "handle_multi_ticket_retry_failed",
    # UI and editing
    "handle_multi_ticket_edit_item",
    "handle_multi_ticket_edit_story",
    "handle_multi_ticket_edit_submit",
    "handle_multi_ticket_remove_item",
    # Cancel handlers
    "handle_multi_ticket_cancel",
    "handle_multi_ticket_cancel_confirm",
    # Linking utilities
    "extract_item_id",
    "extract_story_id",
    "extract_ui_version",
    "_extract_item_id",
    "_extract_story_id",
    "_extract_ui_version",
]
