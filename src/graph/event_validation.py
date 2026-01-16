"""Event validation for workflow steps.

Each WorkflowStep has a set of allowed event actions.
Invalid events return "stale UI" message instead of processing.
"""
import logging
from typing import Optional

from src.schemas.state import WorkflowStep

logger = logging.getLogger(__name__)


# Allowed event actions per workflow step
# Empty set = no workflow actions allowed
ALLOWED_EVENTS: dict[WorkflowStep, set[str]] = {
    WorkflowStep.DRAFT_PREVIEW: {"approve", "reject", "edit"},
    WorkflowStep.MULTI_TICKET_PREVIEW: {"approve", "edit_story", "cancel", "confirm_quantity"},
    WorkflowStep.DECISION_PREVIEW: {"approve", "edit", "cancel"},
    WorkflowStep.REVIEW_ACTIVE: {"show_full", "approve_decision", "turn_into_ticket"},
    WorkflowStep.REVIEW_FROZEN: set(),  # No workflow actions on frozen review
    WorkflowStep.SCOPE_GATE: {"select_review", "select_ticket", "dismiss", "remember"},
}


def validate_event(
    step: Optional[WorkflowStep],
    event_action: str,
) -> bool:
    """Check if event action is allowed for current workflow step.

    Args:
        step: Current workflow step (None if no active workflow)
        event_action: The action being attempted (e.g., "approve", "edit")

    Returns:
        True if event is allowed, False for stale/invalid events
    """
    if step is None:
        # No active workflow - all events invalid
        logger.warning(f"Event '{event_action}' received with no active workflow step")
        return False

    if step not in ALLOWED_EVENTS:
        # Unknown step - defensive
        logger.warning(f"Unknown workflow step: {step}")
        return False

    allowed = event_action in ALLOWED_EVENTS[step]
    if not allowed:
        logger.info(
            f"Stale event detected: '{event_action}' not allowed in step {step.value}. "
            f"Allowed: {ALLOWED_EVENTS[step]}"
        )

    return allowed


def validate_ui_version(
    state_ui_version: int,
    event_ui_version: int,
) -> bool:
    """Check if button click matches current UI version.

    Prevents stale preview button clicks after edit created new version.

    Args:
        state_ui_version: Current ui_version in state
        event_ui_version: ui_version from button click value

    Returns:
        True if versions match, False if stale
    """
    if event_ui_version != state_ui_version:
        logger.info(
            f"Stale UI version: button has v{event_ui_version}, state has v{state_ui_version}"
        )
        return False
    return True


# Stale UI response messages
STALE_EVENT_MESSAGE = "This action is no longer available. The workflow has moved on."
STALE_VERSION_MESSAGE = "This preview is outdated. Please use the current version."
ALREADY_PROCESSED_MESSAGE = "This action was already processed."
