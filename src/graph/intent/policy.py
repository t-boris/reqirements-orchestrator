"""Intent classification policy.

This module contains heuristics for multi-intent detection
that determine when to trigger multi-intent re-classification.

Part of the modularized intent package (Phase 42).
"""
import logging

from src.schemas.intent import IntentResult, has_multi_intent_markers

logger = logging.getLogger(__name__)


# =============================================================================
# Multi-intent detection heuristics (Phase 35)
# Determine when to trigger multi-intent classification.
# =============================================================================

# Action verbs that suggest distinct operations
ACTION_VERBS = [
    "create", "check", "update", "review", "search", "find", "add",
    "delete", "sync", "approve", "reject", "assign", "move", "mark",
]


def should_use_multi_intent_classification(
    message: str,
    single_result: IntentResult,
) -> bool:
    """Determine if message warrants multi-intent classification.

    Signals:
    1. Explicit conjunctions in message
    2. Low confidence on top-1 (< 0.7)
    3. Multiple action verbs detected

    Args:
        message: User's message text
        single_result: Result from single-intent classification

    Returns:
        True if multi-intent classification should be used
    """
    # Signal 1: Conjunctions
    if has_multi_intent_markers(message):
        logger.debug(f"Multi-intent signal: conjunctions detected in '{message[:50]}...'")
        return True

    # Signal 2: Low confidence suggests ambiguity
    if single_result.confidence < 0.7:
        logger.debug(f"Multi-intent signal: low confidence {single_result.confidence}")
        return True

    # Signal 3: Multiple action verbs
    message_lower = message.lower()
    verb_count = sum(1 for verb in ACTION_VERBS if verb in message_lower)
    if verb_count >= 2:
        logger.debug(f"Multi-intent signal: {verb_count} action verbs detected")
        return True

    return False
