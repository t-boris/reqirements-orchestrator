"""Slack-specific types and enums.

Ref: Spec Part 9.1 - Writing Rules
"""
from dataclasses import dataclass
from enum import Enum

from src.domain.types import ChannelId, ThreadTs, UserId


class SlackWriteTarget(str, Enum):
    """Where to write a message."""
    CHANNEL = "channel"       # Visible to everyone, permanent
    THREAD = "thread"         # Conversation context
    EPHEMERAL = "ephemeral"   # Only visible to one user


# Message type -> Target mapping (from spec Part 9.1)
WRITE_TARGETS: dict[str, SlackWriteTarget] = {
    # CHANNEL - Status updates, approved items, decisions
    "entity_proposed": SlackWriteTarget.CHANNEL,
    "entity_approved": SlackWriteTarget.CHANNEL,
    "entity_committed": SlackWriteTarget.CHANNEL,
    "decision_recorded": SlackWriteTarget.CHANNEL,
    "conflict_detected": SlackWriteTarget.CHANNEL,
    "workflow_completed": SlackWriteTarget.CHANNEL,

    # THREAD - Working conversation
    "question_asked": SlackWriteTarget.THREAD,
    "draft_preview": SlackWriteTarget.THREAD,
    "process_progress": SlackWriteTarget.THREAD,
    "plan_status": SlackWriteTarget.THREAD,
    "validation_result": SlackWriteTarget.THREAD,
    "conversation_response": SlackWriteTarget.THREAD,

    # EPHEMERAL - Personal notifications
    "permission_denied": SlackWriteTarget.EPHEMERAL,
    "command_help": SlackWriteTarget.EPHEMERAL,
    "error_message": SlackWriteTarget.EPHEMERAL,
    "queue_position": SlackWriteTarget.EPHEMERAL,
}


@dataclass
class SlackMessage:
    """Slack message reference.

    Ref: Spec Part 9.2
    """
    ts: str                    # Message timestamp (unique ID)
    channel_id: ChannelId
    text: str
    thread_ts: ThreadTs | None = None
    user_id: UserId | None = None
