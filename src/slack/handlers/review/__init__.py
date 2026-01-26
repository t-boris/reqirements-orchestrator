"""Review handlers package.

Handles review-to-ticket, scope gate, and artifact approval flows.

Re-exports all handlers for backward compatibility.
"""

from src.slack.handlers.review.start import (
    handle_review_to_ticket,
    handle_scope_gate_submit,
)

from src.slack.handlers.review.continue_ import (
    show_multi_ticket_preview,
)

from src.slack.handlers.review.architecture import (
    handle_approve_architecture,
)

from src.slack.handlers.review.complete import (
    handle_review_approve,
    handle_turn_into_workitem,
    handle_capture_as_decision,
)

# Alias for plan verification
handle_review_start = handle_review_to_ticket

__all__ = [
    # Start module
    "handle_review_to_ticket",
    "handle_scope_gate_submit",
    "handle_review_start",
    # Continue module
    "show_multi_ticket_preview",
    # Architecture module
    "handle_approve_architecture",
    # Complete module
    "handle_review_approve",
    "handle_turn_into_workitem",
    "handle_capture_as_decision",
]
