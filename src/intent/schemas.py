"""Intent classification schemas.

Ref: BOT_DESIGN.md - Four SuperModes
Ref: RESEARCH.md - Pattern 2: Structured LLM Classification
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class SuperMode(str, Enum):
    """The six SuperModes for message handling.

    Every message results in one of these modes:
    - CREATE: User wants to define a new work item or decision
    - MODIFY: User wants to change an existing entity
    - RECORD: User made a decision that should be captured
    - CONVERSE: Casual conversation, questions, clarifications
    - JIRA: User wants to search, view, update, or query Jira issues
    - ARCHITECT: User asks about software architecture, design patterns, or system design
    """

    CREATE = "create"
    MODIFY = "modify"
    RECORD = "record"
    CONVERSE = "converse"
    JIRA = "jira"
    ARCHITECT = "architect"


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
    WORKSPACE = "workspace"    # Thread has active workspace, route to Orchestrator
    PROCESS = "process"        # Message in known process thread (legacy)
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
    is_compound_request: bool = Field(
        default=False,
        description="True if request requires multiple steps (analyze then create, etc.)"
    )


class SafetyCheckResult(BaseModel):
    """Result of safety evaluation before action execution.

    Ref: CONTEXT.md - Safety Evaluator
    """

    allowed: bool
    reason: str | None = None
    requires_confirmation: bool = False
    warnings: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    """A step in a multi-step execution plan.

    Plans allow the bot to handle compound requests like
    "analyze the architecture and create work items for each component".
    """

    mode: SuperMode = Field(description="The SuperMode to execute for this step")
    instruction: str = Field(description="What the LLM should do in this step")
    pass_output_to_next: bool = Field(
        default=True,
        description="Whether this step's output should be passed as context to the next step"
    )


class ExecutionPlan(BaseModel):
    """Multi-step execution plan for compound requests.

    When a user request requires multiple steps (e.g., "analyze X and create Y"),
    the router generates a plan instead of a single mode classification.
    """

    steps: list[PlanStep] = Field(
        description="Ordered steps to execute",
        min_length=2,  # Plans only make sense with 2+ steps
    )
    reasoning: str = Field(description="Why this request requires a multi-step plan")
