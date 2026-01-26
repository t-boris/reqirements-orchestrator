"""Decision button handlers package.

This package handles all decision-related button interactions:
- decision_approve: Approve a proposed decision -> triggers Jira sync
- decision_edit: Open edit modal for proposed decision
- decision_discard: Delete/discard a proposed decision
- decision_change: Open change modal for approved decision (creates new version)
- decision_deprecate: Open deprecation modal
- decision_history: Show version history
- decision_view: Show decision details
- decision_cancel: Cancel approval/change action

All handlers follow pattern: sync ack() + async via _run_async().

INVARIANT I2: Slack = UI
Handlers are READ-ONLY for truth stores.
Mutations follow truth-first ordering:
  1. Database state update (TRUTH) - must succeed first
  2. Jira sync (PROJECTION) - proceeds regardless of Slack
  3. Slack message (PRESENTATION) - best effort, failures logged not raised
"""
import logging

from src.slack.handlers.decision_buttons.approve import (
    handle_decision_approve,
)
from src.slack.handlers.decision_buttons.change import (
    handle_decision_edit,
    handle_decision_edit_modal_submit,
    handle_decision_change,
    handle_decision_change_modal_submit,
)
from src.slack.handlers.decision_buttons.deprecate import (
    handle_decision_discard,
    handle_decision_deprecate,
    handle_decision_deprecate_modal_submit,
)
from src.slack.handlers.decision_buttons.view import (
    handle_decision_history,
    handle_decision_view,
    handle_decision_cancel,
    handle_decision_show_details,
    handle_decision_hide_details,
)

logger = logging.getLogger(__name__)

__all__ = [
    # Approve
    "handle_decision_approve",
    # Change/Edit
    "handle_decision_edit",
    "handle_decision_edit_modal_submit",
    "handle_decision_change",
    "handle_decision_change_modal_submit",
    # Deprecate/Discard
    "handle_decision_discard",
    "handle_decision_deprecate",
    "handle_decision_deprecate_modal_submit",
    # View/History
    "handle_decision_history",
    "handle_decision_view",
    "handle_decision_cancel",
    "handle_decision_show_details",
    "handle_decision_hide_details",
    # Registration
    "register_decision_handlers",
]


def register_decision_handlers(app):
    """Register all decision button handlers with the Slack app.

    Args:
        app: Slack Bolt App instance
    """
    # Button actions - Approve
    app.action("decision_approve")(handle_decision_approve)

    # Button actions - Edit/Change
    app.action("decision_edit")(handle_decision_edit)
    app.action("decision_change")(handle_decision_change)

    # Button actions - Discard/Deprecate
    app.action("decision_discard")(handle_decision_discard)
    app.action("decision_deprecate")(handle_decision_deprecate)

    # Button actions - View/History
    app.action("decision_history")(handle_decision_history)
    app.action("decision_view")(handle_decision_view)
    app.action("decision_show_details")(handle_decision_show_details)
    app.action("decision_hide_details")(handle_decision_hide_details)
    app.action("decision_cancel")(handle_decision_cancel)

    # Modal submissions
    app.view("decision_edit_modal")(handle_decision_edit_modal_submit)
    app.view("decision_change_modal")(handle_decision_change_modal_submit)
    app.view("decision_deprecate_modal")(handle_decision_deprecate_modal_submit)

    logger.info("Decision button handlers registered")
