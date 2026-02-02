"""Discussion state schema for Phase 45 - Structured Discussion Flow.

Tracks state during architectural discussions to enable:
- Structured questions with button options
- Mid-conversation decision capture via LLM detection
- Completeness-based transition to ticket/decision creation

Design Rule: Only LLM can detect intents and decisions - no regex patterns.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.schemas.decision import DecisionType


class DiscussionPhase(str, Enum):
    """Phase of the structured discussion.

    Tracks progression through the discussion lifecycle.
    """

    EXPLORING = "exploring"  # Initial understanding, gathering context
    DECIDING = "deciding"  # Actively capturing decisions
    READY = "ready"  # Complete enough for action (tickets/decisions)


class CapturedDecision(BaseModel):
    """A decision captured mid-conversation via LLM detection.

    When user answers a question and the LLM detects it contains
    a decision (choice or commitment), it's captured here for later
    formal creation as a Decision entity.

    Example: User answers "1 - long-form Slack message" to a question
    about note delivery format. LLM detects this as an ARCH decision.
    """

    decision_text: str = Field(description="What was decided")
    decision_type: DecisionType = Field(description="Type of decision (ARCH, SCOPE, etc.)")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="LLM's confidence that this is a decision",
    )
    source_question: Optional[str] = Field(
        default=None,
        description="The question that prompted this decision",
    )
    captured_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this decision was captured",
    )
    rationale_hints: list[str] = Field(
        default_factory=list,
        description="Context from conversation for later rich context extraction",
    )


class DiscussionState(BaseModel):
    """State tracked during a structured discussion.

    Enables continuity across multiple exchanges in a discussion thread,
    tracking what's been asked, what decisions have been captured, and
    when the discussion is complete enough to offer transition.
    """

    topic: str = Field(description="What the discussion is about")
    persona: Optional[str] = Field(
        default=None,
        description="Active persona (architect, pm, security) if any",
    )
    phase: DiscussionPhase = Field(
        default=DiscussionPhase.EXPLORING,
        description="Current phase of the discussion",
    )

    # Question tracking
    asked_questions: list[str] = Field(
        default_factory=list,
        description="Question IDs already asked (prevents repeats)",
    )
    pending_question_ids: list[str] = Field(
        default_factory=list,
        description="Question IDs waiting to be asked",
    )

    # Decision tracking
    captured_decisions: list[CapturedDecision] = Field(
        default_factory=list,
        description="Decisions detected mid-conversation",
    )

    # Completeness tracking
    completeness_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Score indicating readiness for transition (0.75+ = ready)",
    )
    completeness_signals: set[str] = Field(
        default_factory=set,
        description="Signals contributing to completeness (e.g., 'has_scope', 'has_constraint')",
    )

    # Conversation context
    key_points: list[str] = Field(
        default_factory=list,
        description="Key points extracted from the discussion",
    )
    constraints_mentioned: list[str] = Field(
        default_factory=list,
        description="Constraints identified during discussion",
    )
    open_questions_text: list[str] = Field(
        default_factory=list,
        description="Questions still unanswered (text, not IDs)",
    )

    # Timestamps
    started_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this discussion started",
    )
    last_activity_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When last activity occurred",
    )

    def has_decisions(self) -> bool:
        """Check if any decisions have been captured."""
        return len(self.captured_decisions) > 0

    def is_ready_for_transition(self, threshold: float = 0.75) -> bool:
        """Check if discussion is complete enough for transition.

        Args:
            threshold: Completeness score threshold (default 0.75)

        Returns:
            True if completeness_score >= threshold
        """
        return self.completeness_score >= threshold

    def add_decision(self, decision: CapturedDecision) -> None:
        """Add a captured decision and update phase.

        Args:
            decision: The captured decision to add
        """
        self.captured_decisions.append(decision)
        self.last_activity_at = datetime.utcnow()

        # Transition to DECIDING phase if we capture a decision
        if self.phase == DiscussionPhase.EXPLORING:
            self.phase = DiscussionPhase.DECIDING

    def mark_question_asked(self, question_id: str) -> None:
        """Mark a question as asked.

        Args:
            question_id: ID of the question that was asked
        """
        if question_id not in self.asked_questions:
            self.asked_questions.append(question_id)
        if question_id in self.pending_question_ids:
            self.pending_question_ids.remove(question_id)
        self.last_activity_at = datetime.utcnow()

    def update_completeness(self, score: float, signals: set[str]) -> None:
        """Update completeness score and signals.

        Args:
            score: New completeness score
            signals: Set of signals contributing to the score
        """
        self.completeness_score = score
        self.completeness_signals = signals
        self.last_activity_at = datetime.utcnow()

        # Transition to READY phase if threshold met
        if self.is_ready_for_transition():
            self.phase = DiscussionPhase.READY
