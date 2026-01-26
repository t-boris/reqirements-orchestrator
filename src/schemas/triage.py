"""Triage schemas for context completeness detection.

Phase 44: Questions-First Collection Stage

TriageContext captures context signals and gaps detected before intent classification.
This enables smart triage - asking targeted questions based on what's actually missing,
not generic checklists.

Key insight from CONTEXT.md:
- Smart triage: Bot reads context, identifies ACTUAL gaps (not generic checklists)
- Fast path: If context is complete, skip questions entirely
- Core win: No more "missing info" loops after routing
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TriageSignal(str, Enum):
    """Context signals detected from message and state.

    These signals indicate what context IS present - the positive indicators
    that help determine if we have enough to proceed.
    """
    HAS_DRAFT = "has_draft"           # Active draft exists
    HAS_ANCHOR = "has_anchor"         # Thread has anchor (workitem/decision)
    HAS_JIRA_KEY = "has_jira_key"     # Message mentions Jira ticket
    HAS_EXPLICIT_MODE = "has_explicit_mode"  # User explicitly said "review", "create", "decide"
    HAS_TOPIC = "has_topic"           # Clear subject/topic extractable
    LOW_CONFIDENCE_MODE = "low_confidence_mode"  # Stage 1 mode score < 0.6


class TriageGap(str, Enum):
    """Gaps in context that may require questions.

    These gaps indicate what context is MISSING - the things we might
    need to ask about before routing.
    """
    UNKNOWN_MODE = "unknown_mode"     # Can't determine BUILD vs THINK vs DECIDE
    UNKNOWN_SCOPE = "unknown_scope"   # Don't know if epic/story/task
    UNKNOWN_TARGET = "unknown_target"  # No clear subject (what are we working on?)
    AMBIGUOUS_INTENT = "ambiguous_intent"  # Multiple interpretations possible
    MISSING_TOPIC = "missing_topic"   # For review, topic unclear


# Configurable threshold for determining fast path
COMPLETENESS_THRESHOLD = 0.7


# Gap severity weights for completeness calculation
_GAP_PENALTIES = {
    TriageGap.UNKNOWN_MODE: 0.2,
    TriageGap.UNKNOWN_TARGET: 0.3,
    TriageGap.AMBIGUOUS_INTENT: 0.2,
    TriageGap.UNKNOWN_SCOPE: 0.15,
    TriageGap.MISSING_TOPIC: 0.1,
}


# Gap to question text mapping
_GAP_QUESTIONS = {
    TriageGap.UNKNOWN_MODE: "What would you like to do? [Create work items] [Get architectural review] [Record a decision]",
    TriageGap.UNKNOWN_TARGET: "What is this about? (provide topic or paste a ticket key)",
    TriageGap.UNKNOWN_SCOPE: "What type of work item? [Epic] [Story] [Task]",
    TriageGap.AMBIGUOUS_INTENT: "I'm not sure what you'd like to do. Could you clarify?",
    TriageGap.MISSING_TOPIC: "What topic should this review focus on?",
}


@dataclass
class TriageContext:
    """Context completeness assessment for triage gate.

    Similar to PreGateOutput but focused on context completeness,
    not safety gates. Used to determine if we should ask questions
    before routing to intent classification.

    Attributes:
        signals: Context signals that were detected (what we have)
        gaps: Context gaps identified (what's missing)
        completeness_score: Float 0-1 computed from signals vs gaps
        suggested_questions: Gap-specific question hints
        fast_path: True if completeness >= threshold (skip questions)
    """
    signals: set[TriageSignal] = field(default_factory=set)
    gaps: set[TriageGap] = field(default_factory=set)
    completeness_score: float = 1.0
    suggested_questions: list[str] = field(default_factory=list)
    fast_path: bool = True

    def has_signal(self, signal: TriageSignal) -> bool:
        """Check if a specific signal is present.

        Args:
            signal: The TriageSignal to check for.

        Returns:
            True if signal is in signals set.
        """
        return signal in self.signals

    def has_gap(self, gap: TriageGap) -> bool:
        """Check if a specific gap is present.

        Args:
            gap: The TriageGap to check for.

        Returns:
            True if gap is in gaps set.
        """
        return gap in self.gaps

    def needs_questions(self) -> bool:
        """Check if questions are needed before routing.

        Returns:
            True if not on fast path (completeness < threshold).
        """
        return not self.fast_path

    def get_priority_gap(self) -> Optional[TriageGap]:
        """Get the highest priority gap to address first.

        Priority order: UNKNOWN_MODE > UNKNOWN_TARGET > AMBIGUOUS_INTENT > others

        Returns:
            The highest priority gap, or None if no gaps.
        """
        priority_order = [
            TriageGap.UNKNOWN_MODE,
            TriageGap.UNKNOWN_TARGET,
            TriageGap.AMBIGUOUS_INTENT,
            TriageGap.UNKNOWN_SCOPE,
            TriageGap.MISSING_TOPIC,
        ]
        for gap in priority_order:
            if gap in self.gaps:
                return gap
        return None

    @classmethod
    def from_gaps_and_signals(
        cls,
        signals: set[TriageSignal],
        gaps: set[TriageGap],
        threshold: float = COMPLETENESS_THRESHOLD,
    ) -> "TriageContext":
        """Create TriageContext with computed completeness score.

        Args:
            signals: Set of detected signals.
            gaps: Set of identified gaps.
            threshold: Completeness threshold for fast path.

        Returns:
            TriageContext with computed fields.
        """
        # Compute completeness score from gaps
        completeness = 1.0
        for gap in gaps:
            penalty = _GAP_PENALTIES.get(gap, 0.1)
            completeness -= penalty
        completeness = max(0.0, min(1.0, completeness))

        # Generate suggested questions from gaps
        suggested_questions = [
            _GAP_QUESTIONS[gap]
            for gap in gaps
            if gap in _GAP_QUESTIONS
        ]

        # Determine fast path
        fast_path = completeness >= threshold

        return cls(
            signals=signals,
            gaps=gaps,
            completeness_score=completeness,
            suggested_questions=suggested_questions,
            fast_path=fast_path,
        )
