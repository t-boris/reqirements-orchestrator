"""ReviewState schema for architecture review conversations.

Phase 37: Unified Question Engine

ReviewState is the structured target for FreeformProvider, analogous to
WorkItemDraft for CatalogProvider. It accumulates context from architecture
review conversations: assumptions, constraints, risks, open questions,
and proposed decisions.
"""
from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, Field


class Assumption(BaseModel):
    """An assumption made during review."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    statement: str
    confidence: float = 0.7  # 0.0-1.0
    source: Optional[str] = None  # "user", "inferred", "default"
    verified: bool = False


class Constraint(BaseModel):
    """A constraint identified during review."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    constraint_type: str = "technical"  # technical, business, timeline, resource
    source: Optional[str] = None


class Risk(BaseModel):
    """A risk identified during review."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    severity: str = "medium"  # low, medium, high, critical
    mitigation: Optional[str] = None
    status: str = "open"  # open, mitigated, accepted


class OpenQuestion(BaseModel):
    """An open question from review."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question: str
    goal: str  # Why we're asking
    maps_to: str  # Which ReviewState field this resolves
    expected_answer_type: str = "text"  # text, choice, number
    options: Optional[list[str]] = None  # For choice type
    answer: Optional[str] = None
    answered_at: Optional[datetime] = None


class ProposedDecision(BaseModel):
    """A decision proposed during review."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    decision_type: str = "arch"  # arch, scope, constraint, priority
    status: str = "proposed"  # proposed, approved, rejected


class ReviewState(BaseModel):
    """Structured state for architecture review conversations.

    This is the target state for FreeformProvider, analogous to
    WorkItemDraft for CatalogProvider.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    channel_id: str
    thread_ts: str

    # Accumulated context from conversation
    assumptions: list[Assumption] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    proposed_decisions: list[ProposedDecision] = Field(default_factory=list)

    # Metadata
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_unanswered_questions(self) -> list[OpenQuestion]:
        """Get questions that haven't been answered."""
        return [q for q in self.open_questions if q.answer is None]

    def get_missing_fields(self) -> list[str]:
        """Determine which areas need more information."""
        missing = []
        if not self.assumptions:
            missing.append("assumptions")
        if not self.constraints:
            missing.append("constraints")
        # risks and decisions can be empty (not missing)
        return missing
