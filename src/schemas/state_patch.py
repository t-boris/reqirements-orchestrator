"""StatePatch model for answer processing in Question Engine.

Provides a unified format for applying user answers to state,
whether from button clicks (deterministic) or text replies (LLM-parsed).
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

# Confidence threshold - below this, ask for clarification
CONFIDENCE_THRESHOLD = 0.7


class AnswerSource(str, Enum):
    """Source of the answer - determines confidence level.

    BUTTON: User clicked a button (deterministic, confidence=1.0)
    TEXT: User typed a text reply (LLM-parsed, variable confidence)
    """

    BUTTON = "button"
    TEXT = "text"


class StatePatch(BaseModel):
    """A patch to apply to state from a user answer.

    Represents a single field update with its source and confidence.
    Patches with confidence below CONFIDENCE_THRESHOLD may trigger clarification.
    """

    field: str = Field(description="Target field to update (e.g., 'scope', 'acceptance_criteria')")
    value: Any = Field(description="New value to apply")
    source: AnswerSource = Field(description="How the answer was provided")
    confidence: float = Field(default=1.0, description="1.0 for buttons, LLM score for text")
    question_id: Optional[str] = Field(default=None, description="Which question this answers")
    raw_input: Optional[str] = Field(default=None, description="Original user input")


class StatePatchResult(BaseModel):
    """Result of applying patches to state.

    Tracks which patches were applied, any errors encountered,
    and whether clarification is needed for low-confidence patches.
    """

    success: bool = Field(description="Whether all patches were applied successfully")
    patches_applied: list[StatePatch] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    needs_clarification: bool = Field(default=False, description="If confidence too low")
    clarification_question: Optional[str] = Field(default=None)


def create_button_patch(
    field: str,
    value: Any,
    question_id: str,
) -> StatePatch:
    """Create deterministic patch from button click.

    Button clicks are always high confidence since the user made an explicit choice.

    Args:
        field: The field to update
        value: The value to set
        question_id: ID of the question being answered

    Returns:
        StatePatch with confidence=1.0 and source=BUTTON
    """
    return StatePatch(
        field=field,
        value=value,
        source=AnswerSource.BUTTON,
        confidence=1.0,
        question_id=question_id,
    )
