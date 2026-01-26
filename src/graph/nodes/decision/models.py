"""Decision node models and types."""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class DecisionResult(BaseModel):
    """Result of decision node processing."""
    action: Literal["ask", "preview", "ready_to_create", "preflight_required", "draft_refine"]
    questions: list[str] = Field(default_factory=list)  # For ASK action
    reason: str = ""  # Why this decision
    is_reask: bool = False  # True if re-asking unanswered questions
    reask_count: int = 0  # How many times we've re-asked
    potential_duplicates: list[dict] = Field(default_factory=list)  # Similar tickets found
    bound_ticket: Optional[str] = None  # Existing ticket this thread is bound to
    preflight_result: Optional[dict] = None  # PreflightResult dict for blocking duplicates
    refinement_prompt: Optional[str] = None  # For DRAFT_REFINE: question to ask user
