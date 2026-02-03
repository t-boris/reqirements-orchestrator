"""Intent classification module.

Two-stage intent classification:
1. PreGates - Deterministic routing for commands, actions, approvals
2. LLM Router - Classification for everything else

Plus Safety Evaluator between router and action execution.

Ref: BOT_DESIGN.md - Two-Stage Intent Classification
Ref: RESEARCH.md - Pattern 1: PreGates
Ref: CONTEXT.md - Safety Evaluator
"""

from src.intent.schemas import (
    SuperMode,
    EntityType,
    IntentClassification,
    PreGateResult,
    PreGateOutput,
    SafetyCheckResult,
)
from src.intent.pregates import check_pregates
from src.intent.router import classify_intent, RouterContext
from src.intent.safety import (
    ActionContext,
    evaluate_safety,
    evaluate_approval_safety,
    evaluate_commit_safety,
    evaluate_objection_safety,
)

__all__ = [
    # Schemas
    "SuperMode",
    "EntityType",
    "IntentClassification",
    "PreGateResult",
    "PreGateOutput",
    "SafetyCheckResult",
    # PreGates
    "check_pregates",
    # Router
    "classify_intent",
    "RouterContext",
    # Safety
    "ActionContext",
    "evaluate_safety",
    "evaluate_approval_safety",
    "evaluate_commit_safety",
    "evaluate_objection_safety",
]
