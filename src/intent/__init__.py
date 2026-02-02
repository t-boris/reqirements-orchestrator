"""Intent classification module.

Two-stage intent classification:
1. PreGates - Deterministic routing for commands, actions, approvals
2. LLM Router - Classification for everything else

Ref: BOT_DESIGN.md - Two-Stage Intent Classification
Ref: RESEARCH.md - Pattern 1: PreGates
"""

from src.intent.schemas import (
    SuperMode,
    IntentClassification,
    PreGateResult,
    PreGateOutput,
)
from src.intent.pregates import check_pregates

__all__ = [
    "SuperMode",
    "IntentClassification",
    "PreGateResult",
    "PreGateOutput",
    "check_pregates",
]
