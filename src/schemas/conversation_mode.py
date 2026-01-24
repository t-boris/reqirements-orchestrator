"""ConversationMode state machine for Question Engine.

Controls when the bot leads (ACTIVE) vs listens (PASSIVE) in a conversation.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# Maximum unanswered questions before showing partial preview
QUESTION_BUDGET = 2


class ConversationMode(str, Enum):
    """Bot conversation mode - active vs passive engagement.

    ACTIVE: Bot leads conversation, posts questions, follows up
    PASSIVE: Bot listens, acknowledges, doesn't ask unprompted
    """

    ACTIVE = "active"
    PASSIVE = "passive"


class ModeTransitionReason(str, Enum):
    """Reasons for mode transitions (for logging and audit)."""

    MENTION = "mention"  # User @mentioned bot
    COMMAND = "command"  # /command invoked
    TASK_BLOCKED = "task_blocked"  # TaskPlan task became BLOCKED
    PLAN_COMPLETE = "plan_complete"  # TaskPlan finished (DONE or CANCELED)
    TIMEOUT = "timeout"  # 10min without user response
    USER_CANCEL = "user_cancel"  # User explicitly canceled


class ConversationModeState(BaseModel):
    """State for conversation mode tracking.

    Tracks the current mode, when it was entered, and activity metrics
    for timeout detection and question budget tracking.
    """

    channel_id: str
    thread_ts: str
    mode: ConversationMode = Field(default=ConversationMode.PASSIVE)
    entered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    unanswered_questions: int = Field(default=0)
    transition_reason: Optional[ModeTransitionReason] = None


def should_activate(reason: ModeTransitionReason) -> bool:
    """Check if reason should transition to ACTIVE mode.

    Args:
        reason: The transition reason to evaluate

    Returns:
        True if the reason triggers activation
    """
    return reason in (
        ModeTransitionReason.MENTION,
        ModeTransitionReason.COMMAND,
        ModeTransitionReason.TASK_BLOCKED,
    )


def should_deactivate(reason: ModeTransitionReason) -> bool:
    """Check if reason should transition to PASSIVE mode.

    Args:
        reason: The transition reason to evaluate

    Returns:
        True if the reason triggers deactivation
    """
    return reason in (
        ModeTransitionReason.PLAN_COMPLETE,
        ModeTransitionReason.TIMEOUT,
        ModeTransitionReason.USER_CANCEL,
    )
