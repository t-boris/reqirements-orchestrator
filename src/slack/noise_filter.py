"""Low-noise filtering for Slack messages.

Determines when MARO should respond vs stay silent.
Applies low-noise principle: don't reply to every message.

Key behaviors:
- Always respond if directly @mentioned
- Always respond if there's a pending action
- Always respond to slash commands
- In listening mode: only respond to high-confidence actionable content
- Prefer silence over spam (conservative detection)

Phase 27.6 - Notifications & Slack UX (R23 Low-noise)
"""
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def should_respond(
    message_text: str,
    bot_user_id: str,
    is_listening_mode: bool = False,
    has_pending_action: bool = False,
) -> Tuple[bool, str]:
    """Determine if MARO should respond to this message.

    Applies low-noise filtering to reduce bot spam while ensuring
    important messages get responses.

    Args:
        message_text: The message text to analyze
        bot_user_id: The bot's Slack user ID
        is_listening_mode: Whether the channel is in listening mode
        has_pending_action: Whether there's a pending action in this thread

    Returns:
        Tuple of (should_respond: bool, reason: str)
        Reason explains why the decision was made (for debugging)

    Examples:
        >>> should_respond("<@U123BOT> help", "U123BOT")
        (True, "direct_mention")

        >>> should_respond("how was your weekend", "U123BOT", is_listening_mode=True)
        (False, "listening_mode_noise")

        >>> should_respond("we need to track this issue", "U123BOT", is_listening_mode=True)
        (True, "high_confidence_actionable")
    """
    # Always respond if directly @mentioned
    if f"<@{bot_user_id}>" in message_text:
        return True, "direct_mention"

    # Always respond if there's a pending action
    if has_pending_action:
        return True, "pending_action"

    # Check for slash command (starts with /maro)
    stripped = message_text.strip()
    if stripped.startswith("/maro"):
        return True, "slash_command"

    # Check for MARO name mention (case insensitive)
    if re.search(r'\bmaro\b', message_text, re.IGNORECASE):
        return True, "name_mention"

    # In listening mode, only respond to high-confidence actionable items
    if is_listening_mode:
        if _is_high_confidence_actionable(message_text):
            return True, "high_confidence_actionable"
        return False, "listening_mode_noise"

    # Not in listening mode, not mentioned - don't respond
    return False, "not_mentioned"


def _is_high_confidence_actionable(text: str) -> bool:
    """Check if message is high-confidence actionable.

    Conservative detection - prefer false negatives over spam.
    Only returns True for messages that strongly signal intent
    to create tasks, track work, or make decisions.

    Args:
        text: Message text to analyze

    Returns:
        True if high confidence actionable content detected
    """
    text_lower = text.lower()

    # Explicit task creation signals
    task_signals = [
        r"\bwe need to\b",
        r"\bshould create\b",
        r"\baction item[s]?\b",
        r"\btodo[s]?\s*:",
        r"\bticket[s]? for\b",
        r"\bfile (a|an) (bug|issue|ticket)\b",
        r"\btrack(ing)? this\b",
        r"\bcreate (a|an) (story|task|bug|ticket)\b",
        r"\bopen (a|an) (issue|ticket)\b",
        r"\blet'?s (add|create|open)\b",
    ]

    for pattern in task_signals:
        if re.search(pattern, text_lower):
            return True

    # Decision signals
    decision_signals = [
        r"\bwe decided\b",
        r"\bdecision:\b",
        r"\bagreed (to|on|that)\b",
        r"\blet'?s go with\b",
        r"\bfinal decision\b",
        r"\bwe'?re going with\b",
    ]

    for pattern in decision_signals:
        if re.search(pattern, text_lower):
            return True

    # Requirement signals
    requirement_signals = [
        r"\brequirement:\b",
        r"\bmust (have|be|include)\b",
        r"\bconstraint:\b",
        r"\bacceptance criteria\b",
    ]

    for pattern in requirement_signals:
        if re.search(pattern, text_lower):
            return True

    return False


def format_skipped_reason(reason: str) -> Optional[str]:
    """Format reason for skipping response (for debug mode).

    Args:
        reason: The reason code from should_respond

    Returns:
        Human-readable explanation or None if not a skip reason
    """
    reasons = {
        "listening_mode_noise": "Skipped: listening mode, no actionable content detected",
        "not_mentioned": "Skipped: not @mentioned",
    }
    return reasons.get(reason)


def is_actionable(text: str) -> bool:
    """Public wrapper to check if text contains actionable content.

    Useful for features that need to detect actionable messages
    without the full should_respond logic.

    Args:
        text: Message text to analyze

    Returns:
        True if actionable content detected
    """
    return _is_high_confidence_actionable(text)


def get_actionable_signals(text: str) -> list[str]:
    """Get list of actionable signals found in text.

    Useful for debugging/explaining why a message was flagged.

    Args:
        text: Message text to analyze

    Returns:
        List of signal names found (empty if none)
    """
    signals = []
    text_lower = text.lower()

    # Check task signals
    task_patterns = {
        "need_to": r"\bwe need to\b",
        "should_create": r"\bshould create\b",
        "action_item": r"\baction item[s]?\b",
        "todo": r"\btodo[s]?\s*:",
        "ticket_for": r"\bticket[s]? for\b",
        "file_issue": r"\bfile (a|an) (bug|issue|ticket)\b",
        "tracking": r"\btrack(ing)? this\b",
        "create_story": r"\bcreate (a|an) (story|task|bug|ticket)\b",
        "open_issue": r"\bopen (a|an) (issue|ticket)\b",
        "lets_create": r"\blet'?s (add|create|open)\b",
    }

    for name, pattern in task_patterns.items():
        if re.search(pattern, text_lower):
            signals.append(f"task:{name}")

    # Check decision signals
    decision_patterns = {
        "we_decided": r"\bwe decided\b",
        "decision_label": r"\bdecision:\b",
        "agreed": r"\bagreed (to|on|that)\b",
        "go_with": r"\blet'?s go with\b",
        "final_decision": r"\bfinal decision\b",
        "going_with": r"\bwe'?re going with\b",
    }

    for name, pattern in decision_patterns.items():
        if re.search(pattern, text_lower):
            signals.append(f"decision:{name}")

    # Check requirement signals
    requirement_patterns = {
        "requirement_label": r"\brequirement:\b",
        "must_have": r"\bmust (have|be|include)\b",
        "constraint_label": r"\bconstraint:\b",
        "acceptance_criteria": r"\bacceptance criteria\b",
    }

    for name, pattern in requirement_patterns.items():
        if re.search(pattern, text_lower):
            signals.append(f"requirement:{name}")

    return signals
