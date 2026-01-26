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

logger = logging.getLogger(__name__)

__all__ = [
    # Approve
    "handle_decision_approve",
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

    logger.info("Decision button handlers registered")
