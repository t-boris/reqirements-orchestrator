"""Question schemas for the Question Engine.

Phase 36: Question Engine - Conversation Driver

QuestionTask extends TaskPlan with question-specific fields. Questions become
first-class tasks with typed question types, target fields, options, and
status tracking.
"""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    """Type of question being asked.

    Determines the UI presentation and expected answer format.
    """
    CONFIRM_SCOPE = "confirm_scope"      # Choice from known options (parent selection, scope)
    COLLECT_FIELD = "collect_field"      # Get specific field value (acceptance criteria, title)
    RESOLVE_CONFLICT = "resolve_conflict"  # Pick A or B for conflict resolution
    ASK_USER = "ask_user"                # Freeform fallback when no template fits


class QuestionStatus(str, Enum):
    """Status of a question.

    Tracks whether the question has been answered.
    """
    PENDING = "pending"      # Not yet answered
    ANSWERED = "answered"    # User provided answer
    SKIPPED = "skipped"      # Bypassed due to budget or user choice


class QuestionOption(BaseModel):
    """An option for multiple-choice questions.

    Used with CONFIRM_SCOPE and RESOLVE_CONFLICT question types.
    """
    option_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str  # Button text
    description: Optional[str] = None  # Longer description
    value: Any = None  # The actual value to apply
    is_recommended: bool = False  # Highlight as recommended


class QuestionTask(BaseModel):
    """A question task within a TaskPlan.

    Questions are specialized tasks that pause execution to gather user input.
    They have typed question formats, optional choices, and track answers.
    """
    question_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question_type: QuestionType
    question_text: str  # The actual question to display
    target_field: Optional[str] = None  # For COLLECT_FIELD, which draft field we're filling
    options: Optional[list[QuestionOption]] = None  # For CONFIRM_SCOPE/RESOLVE_CONFLICT
    priority: int = Field(default=100)  # Lower = ask first
    status: QuestionStatus = QuestionStatus.PENDING
    answer: Optional[str] = None  # User's answer once provided
    answered_at: Optional[datetime] = None
    answered_by: Optional[str] = None  # user_id

    def is_answered(self) -> bool:
        """Check if this question has been answered.

        Returns:
            True if status is ANSWERED, False otherwise.
        """
        return self.status == QuestionStatus.ANSWERED

    def is_pending(self) -> bool:
        """Check if this question is still pending.

        Returns:
            True if status is PENDING, False otherwise.
        """
        return self.status == QuestionStatus.PENDING

    def has_options(self) -> bool:
        """Check if this question has options.

        Returns:
            True if options list is not empty, False otherwise.
        """
        return self.options is not None and len(self.options) > 0
