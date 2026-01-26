"""Triage gate for detecting context completeness before intent classification.

Phase 44: Questions-First Collection Stage

This module provides deterministic (no LLM) detection of context signals and gaps.
It runs BEFORE intent classification to determine if we have enough context to
route properly, or if we need to ask questions first.

Key design principles:
- No LLM calls - this is a fast gate
- Deterministic signal detection from state and message patterns
- Gap detection based on what signals are missing
- Completeness scoring to determine fast path vs questions needed
"""
import logging
import re
from typing import TYPE_CHECKING, Optional

from src.schemas.triage import (
    TriageContext,
    TriageSignal,
    TriageGap,
    COMPLETENESS_THRESHOLD,
)

if TYPE_CHECKING:
    from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


# Jira key pattern for detecting ticket references
JIRA_KEY_PATTERN = re.compile(r'\b([A-Z][A-Z0-9]+-\d+)\b')

# Explicit mode keywords - user clearly states their intent
EXPLICIT_MODE_PATTERNS = {
    'review': re.compile(r'\b(review|analyze|look at|examine|assess|evaluate)\b', re.IGNORECASE),
    'create': re.compile(r'\b(create|make|add|build|draft|write|new)\s+(ticket|story|epic|task|issue|item|bug)\b', re.IGNORECASE),
    'decide': re.compile(r'\b(decide|decision|agree|we agreed|let\'s go with|approved)\b', re.IGNORECASE),
}

# Topic extraction patterns - looks for subject after common prepositions
TOPIC_PATTERNS = [
    re.compile(r'\b(?:about|regarding|for|on|concerning)\s+([^.!?\n]{5,50})', re.IGNORECASE),
    re.compile(r'\b(?:the|this|our)\s+(\w+(?:\s+\w+){0,3})\s+(?:feature|project|system|service|module|api)', re.IGNORECASE),
]


def detect_signals(
    state: "AgentState",
    message: str,
    mode_score: Optional[float] = None,
) -> set[TriageSignal]:
    """Detect context signals from state and message.

    Signals indicate what context IS present - the positive indicators
    that help determine if we have enough to proceed.

    Args:
        state: Current AgentState with draft, anchor, etc.
        message: User's message text.
        mode_score: Optional Stage 1 mode confidence score.

    Returns:
        Set of detected TriageSignals.
    """
    signals: set[TriageSignal] = set()

    # Check for active draft
    draft = state.get("draft")
    structured_draft = state.get("structured_draft")
    if draft or structured_draft:
        has_content = False
        if draft and hasattr(draft, 'title') and draft.title:
            has_content = True
        if structured_draft and hasattr(structured_draft, 'items') and structured_draft.items:
            has_content = True
        if has_content:
            signals.add(TriageSignal.HAS_DRAFT)
            logger.debug("Signal detected: HAS_DRAFT")

    # Check for thread anchor (workitem, decision, etc.)
    thread_context = state.get("thread_context")
    if thread_context:
        object_id = getattr(thread_context, 'object_id', None) or thread_context.get('object_id') if isinstance(thread_context, dict) else None
        if object_id:
            signals.add(TriageSignal.HAS_ANCHOR)
            logger.debug("Signal detected: HAS_ANCHOR")

    # Check for Jira key in message
    if JIRA_KEY_PATTERN.search(message):
        signals.add(TriageSignal.HAS_JIRA_KEY)
        logger.debug("Signal detected: HAS_JIRA_KEY")

    # Check for explicit mode keywords
    for mode_name, pattern in EXPLICIT_MODE_PATTERNS.items():
        if pattern.search(message):
            signals.add(TriageSignal.HAS_EXPLICIT_MODE)
            logger.debug(f"Signal detected: HAS_EXPLICIT_MODE ({mode_name})")
            break

    # Check for extractable topic
    for pattern in TOPIC_PATTERNS:
        match = pattern.search(message)
        if match and len(match.group(1).strip()) >= 5:
            signals.add(TriageSignal.HAS_TOPIC)
            logger.debug(f"Signal detected: HAS_TOPIC ({match.group(1).strip()[:20]}...)")
            break

    # Check for low confidence mode (Stage 1 score)
    if mode_score is not None and mode_score < 0.6:
        signals.add(TriageSignal.LOW_CONFIDENCE_MODE)
        logger.debug(f"Signal detected: LOW_CONFIDENCE_MODE (score={mode_score})")

    return signals


def detect_gaps(
    signals: set[TriageSignal],
    message: str,
) -> set[TriageGap]:
    """Detect context gaps based on what signals are missing.

    Gaps indicate what context is MISSING - the things we might
    need to ask about before routing.

    Args:
        signals: Set of detected signals.
        message: User's message text.

    Returns:
        Set of detected TriageGaps.
    """
    gaps: set[TriageGap] = set()
    word_count = len(message.split())

    # UNKNOWN_MODE: Can't determine intent without explicit mode or draft context
    if TriageSignal.HAS_EXPLICIT_MODE not in signals and TriageSignal.HAS_DRAFT not in signals:
        # If also low confidence mode, this is a strong signal of unknown mode
        if TriageSignal.LOW_CONFIDENCE_MODE in signals:
            gaps.add(TriageGap.UNKNOWN_MODE)
            logger.debug("Gap detected: UNKNOWN_MODE (no explicit mode + low confidence)")

    # UNKNOWN_TARGET: No clear subject to work on
    if (TriageSignal.HAS_ANCHOR not in signals and
        TriageSignal.HAS_JIRA_KEY not in signals and
        TriageSignal.HAS_TOPIC not in signals):
        gaps.add(TriageGap.UNKNOWN_TARGET)
        logger.debug("Gap detected: UNKNOWN_TARGET (no anchor, jira key, or topic)")

    # AMBIGUOUS_INTENT: Short message with no clear signals
    if word_count < 10:
        significant_signals = signals - {TriageSignal.LOW_CONFIDENCE_MODE}
        if len(significant_signals) == 0:
            gaps.add(TriageGap.AMBIGUOUS_INTENT)
            logger.debug(f"Gap detected: AMBIGUOUS_INTENT (short message with {len(significant_signals)} signals)")

    # MISSING_TOPIC: For review mode, topic should be clear
    # This is detected when we have review mode explicitly but no topic
    if TriageSignal.HAS_EXPLICIT_MODE in signals and TriageSignal.HAS_TOPIC not in signals:
        # Check if it's specifically a review request
        if EXPLICIT_MODE_PATTERNS['review'].search(message):
            gaps.add(TriageGap.MISSING_TOPIC)
            logger.debug("Gap detected: MISSING_TOPIC (review mode without topic)")

    return gaps


def compute_completeness(
    signals: set[TriageSignal],
    gaps: set[TriageGap],
) -> float:
    """Compute context completeness score from signals and gaps.

    Starts at 1.0 and subtracts penalties for each gap.
    Result is clamped to [0.0, 1.0].

    Args:
        signals: Set of detected signals (for context, not used in calculation).
        gaps: Set of identified gaps.

    Returns:
        Float completeness score between 0.0 and 1.0.
    """
    # Gap penalties (from triage schema)
    penalties = {
        TriageGap.UNKNOWN_MODE: 0.2,
        TriageGap.UNKNOWN_TARGET: 0.3,
        TriageGap.AMBIGUOUS_INTENT: 0.2,
        TriageGap.UNKNOWN_SCOPE: 0.15,
        TriageGap.MISSING_TOPIC: 0.1,
    }

    completeness = 1.0
    for gap in gaps:
        penalty = penalties.get(gap, 0.1)
        completeness -= penalty
        logger.debug(f"Completeness penalty: {gap.value} = -{penalty}")

    completeness = max(0.0, min(1.0, completeness))
    logger.debug(f"Final completeness score: {completeness}")

    return completeness


# Gap-to-question mapping
_GAP_QUESTIONS = {
    TriageGap.UNKNOWN_MODE: "What would you like to do? [Create work items] [Get architectural review] [Record a decision]",
    TriageGap.UNKNOWN_TARGET: "What is this about? (provide topic or paste a ticket key)",
    TriageGap.UNKNOWN_SCOPE: "What type of work item? [Epic] [Story] [Task]",
    TriageGap.AMBIGUOUS_INTENT: "I'm not sure what you'd like to do. Could you clarify?",
    TriageGap.MISSING_TOPIC: "What topic should this review focus on?",
}


def generate_questions(gaps: set[TriageGap]) -> list[str]:
    """Generate suggested questions from detected gaps.

    Args:
        gaps: Set of identified gaps.

    Returns:
        List of question strings, one per gap.
    """
    return [_GAP_QUESTIONS[gap] for gap in gaps if gap in _GAP_QUESTIONS]


def check_triage_needed(
    state: "AgentState",
    message: str,
    mode_score: Optional[float] = None,
    threshold: float = COMPLETENESS_THRESHOLD,
) -> TriageContext:
    """Main entry point: Check if triage questions are needed before routing.

    This is the primary function to call before intent classification.
    It detects signals, identifies gaps, computes completeness, and
    determines if we should ask questions or proceed directly.

    Args:
        state: Current AgentState.
        message: User's message text.
        mode_score: Optional Stage 1 mode confidence score.
        threshold: Completeness threshold for fast path (default 0.7).

    Returns:
        TriageContext with signals, gaps, completeness_score, and fast_path.
    """
    logger.info("Running triage gate check")

    # Step 1: Detect signals
    signals = detect_signals(state, message, mode_score)
    logger.info(f"Detected signals: {[s.value for s in signals]}")

    # Step 2: Detect gaps
    gaps = detect_gaps(signals, message)
    logger.info(f"Detected gaps: {[g.value for g in gaps]}")

    # Step 3: Compute completeness
    completeness = compute_completeness(signals, gaps)

    # Step 4: Generate suggested questions
    suggested_questions = generate_questions(gaps)

    # Step 5: Determine fast path
    fast_path = completeness >= threshold

    logger.info(f"Triage result: completeness={completeness:.2f}, fast_path={fast_path}")

    return TriageContext(
        signals=signals,
        gaps=gaps,
        completeness_score=completeness,
        suggested_questions=suggested_questions,
        fast_path=fast_path,
    )
