"""Intent classification schemas.

Ref: BOT_DESIGN.md - Four SuperModes
Ref: RESEARCH.md - Pattern 2: Structured LLM Classification
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class SuperMode(str, Enum):
    """The four SuperModes for message handling.

    Every message results in one of these modes:
    - CREATE: User wants to define a new work item or decision
    - MODIFY: User wants to change an existing entity
    - RECORD: User made a decision that should be captured
    - CONVERSE: Casual conversation, questions, clarifications
    """

    CREATE = "create"
    MODIFY = "modify"
    RECORD = "record"
    CONVERSE = "converse"


class EntityType(str, Enum):
    """Types of entities that can be created or modified."""

    WORK_ITEM = "work_item"
    DECISION = "decision"


class PreGateResult(str, Enum):
    """Result of PreGate check - deterministic routing before LLM.

    Ref: RESEARCH.md - Pattern 1: PreGates (Deterministic Pre-Routing)
    """

    COMMAND = "command"        # Slash command detected (/maro)
    ACTION = "action"          # Button click detected (block_actions event)
    APPROVAL = "approval"      # Explicit approve/object keyword
    PROCESS = "process"        # Message in known process thread
    BOT_MESSAGE = "bot"        # Message from bot (ignore)
    PASS_THROUGH = "pass"      # Needs LLM classification


class PreGateOutput(BaseModel):
    """Output from PreGate check."""

    result: PreGateResult
    data: dict | None = None

    class Config:
        frozen = True


class IntentClassification(BaseModel):
    """LLM classification output schema.

    Ref: RESEARCH.md - Pattern 2: Structured LLM Classification
    Ref: BOT_DESIGN.md - Intent Classification Prompt
    """

    mode: SuperMode
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence")
    entity_type: EntityType | None = Field(
        default=None,
        description="Type of entity for CREATE/MODIFY modes"
    )
    target_entity_id: str | None = Field(
        default=None,
        description="ID of entity for MODIFY mode"
    )
    reasoning: str = Field(description="Brief explanation of classification")
    entities_mentioned: list[str] = Field(
        default_factory=list,
        description="Entity IDs mentioned in the message"
    )


class SafetyCheckResult(BaseModel):
    """Result of safety evaluation before action execution.

    Ref: CONTEXT.md - Safety Evaluator
    """

    allowed: bool
    reason: str | None = None
    requires_confirmation: bool = False
    warnings: list[str] = Field(default_factory=list)
