"""Unified intent classification output (Phase 39).

IntentEnvelope replaces fragmented IntentResult/TaskPlanProposal
with unified format supporting single/plan/ambiguous kinds.
"""
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.schemas.intent import Intent, SuperMode


class RiskLevel(str, Enum):
    """Risk classification for intents."""
    SAFE = "safe"           # Read-only, analysis, discussion
    WRITE = "write"         # Single Jira write
    MASS_WRITE = "mass_write"   # Multiple Jira writes
    DESTRUCTIVE = "destructive"  # Delete, irreversible changes


class EnvelopeKind(str, Enum):
    """Kind of intent envelope."""
    SINGLE = "single"       # Single action
    PLAN = "plan"           # Multiple tasks
    AMBIGUOUS = "ambiguous" # Requires user choice


class TargetReference(BaseModel):
    """Explicit target references extracted from message."""
    jira_key: Optional[str] = None
    decision_id: Optional[str] = None
    workitem_id: Optional[str] = None


class IntentCandidate(BaseModel):
    """Single intent candidate with score."""
    mode: SuperMode
    intent: Intent
    score: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.SAFE
    targets: TargetReference = Field(default_factory=TargetReference)
    reason: str = ""


class TaskEnvelope(BaseModel):
    """Single task within a plan envelope."""
    mode: SuperMode
    intent: Intent
    risk_level: RiskLevel
    targets: TargetReference = Field(default_factory=TargetReference)
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    depends_on: list[int] = Field(default_factory=list)  # Task indices


class AmbiguousChoice(BaseModel):
    """Choice option for ambiguous envelope."""
    label: str
    mode: SuperMode
    intent: Intent
    risk_level: RiskLevel
    targets: TargetReference = Field(default_factory=TargetReference)
    params: dict[str, Any] = Field(default_factory=dict)


class IntentEnvelope(BaseModel):
    """Unified intent classification output.

    Three kinds:
    - single: One clear intent with high confidence
    - plan: Multiple tasks from compound request
    - ambiguous: Low margin or unclear, requires user choice
    """
    kind: EnvelopeKind

    # For kind=single
    mode: Optional[SuperMode] = None
    intent: Optional[Intent] = None
    targets: TargetReference = Field(default_factory=TargetReference)
    params: dict[str, Any] = Field(default_factory=dict)

    # For kind=plan
    tasks: list[TaskEnvelope] = Field(default_factory=list)
    requires_confirm: bool = False  # True if any task has write risk

    # For kind=ambiguous
    choices: list[AmbiguousChoice] = Field(default_factory=list)

    # Metrics (always present)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    margin: float = Field(ge=0.0, le=1.0, default=0.0)  # top - second
    risk_level: RiskLevel = RiskLevel.SAFE

    # Alternatives for transparency
    alternatives: list[IntentCandidate] = Field(default_factory=list)

    # Explanations
    reason: str = ""

    @classmethod
    def single(
        cls,
        mode: SuperMode,
        intent: Intent,
        confidence: float,
        margin: float,
        risk_level: RiskLevel = RiskLevel.SAFE,
        targets: Optional[TargetReference] = None,
        params: Optional[dict] = None,
        reason: str = "",
        alternatives: Optional[list[IntentCandidate]] = None,
    ) -> "IntentEnvelope":
        """Factory for single-action envelope."""
        return cls(
            kind=EnvelopeKind.SINGLE,
            mode=mode,
            intent=intent,
            confidence=confidence,
            margin=margin,
            risk_level=risk_level,
            targets=targets or TargetReference(),
            params=params or {},
            reason=reason,
            alternatives=alternatives or [],
        )

    @classmethod
    def plan(
        cls,
        tasks: list[TaskEnvelope],
        confidence: float,
        margin: float,
        requires_confirm: bool = False,
        reason: str = "",
    ) -> "IntentEnvelope":
        """Factory for multi-task plan envelope."""
        # Risk = max risk of all tasks
        max_risk = RiskLevel.SAFE
        risk_order = [RiskLevel.SAFE, RiskLevel.WRITE, RiskLevel.MASS_WRITE, RiskLevel.DESTRUCTIVE]
        for task in tasks:
            if risk_order.index(task.risk_level) > risk_order.index(max_risk):
                max_risk = task.risk_level
        return cls(
            kind=EnvelopeKind.PLAN,
            tasks=tasks,
            confidence=confidence,
            margin=margin,
            risk_level=max_risk,
            requires_confirm=requires_confirm or max_risk != RiskLevel.SAFE,
            reason=reason,
        )

    @classmethod
    def ambiguous(
        cls,
        choices: list[AmbiguousChoice],
        reason: str,
        confidence: float = 0.5,
        margin: float = 0.0,
    ) -> "IntentEnvelope":
        """Factory for ambiguous envelope requiring user choice."""
        return cls(
            kind=EnvelopeKind.AMBIGUOUS,
            choices=choices,
            confidence=confidence,
            margin=margin,
            risk_level=RiskLevel.SAFE,  # No action until user chooses
            reason=reason,
        )

    def to_legacy_intent_result(self) -> "IntentResult":
        """Convert to legacy IntentResult for backward compatibility.

        DEPRECATED: Use IntentEnvelope directly in new code.
        """
        from src.schemas.intent import IntentResult

        if self.kind == EnvelopeKind.SINGLE:
            return IntentResult(
                intent=self.intent or Intent.REVIEW,
                confidence=self.confidence,
                super_mode=self.mode,
                reasons=[self.reason] if self.reason else [],
            )
        elif self.kind == EnvelopeKind.PLAN and self.tasks:
            top = self.tasks[0]
            return IntentResult(
                intent=top.intent,
                confidence=self.confidence,
                super_mode=top.mode,
                reasons=[self.reason] if self.reason else [],
            )
        else:
            return IntentResult(
                intent=Intent.AMBIGUOUS,
                confidence=self.confidence,
                super_mode=SuperMode.CHAT,
                reasons=[self.reason] if self.reason else [],
            )
