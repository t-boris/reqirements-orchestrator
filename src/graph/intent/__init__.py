"""Intent classification package.

This package provides intent classification for user messages.
It's the modularized version of the original intent.py (Phase 42).

Public API:
- classify_intent: Main classification function
- classify_intent_with_context: Context-aware classification
- classify_intent_v2: Phase 39 router wrapper
- intent_router_node: LangGraph node for intent routing
- get_intent_classifier: Factory for classifier selection
- should_use_multi_intent_classification: Multi-intent detection

Internal modules:
- pre_gates: Decision type detection
- mode_classifier: Stage 1 mode classification
- intent_classifier: Stage 2 intent extraction
- policy: Ambiguity policy
- router: Main entry points and graph node
"""

# Re-export from router (main entry points)
from src.graph.intent.router import (
    classify_intent,
    classify_intent_with_context,
    classify_intent_v2,
    intent_router_node,
    get_intent_classifier,
    should_use_multi_intent_classification,
    run_pre_gates,
    # Legacy alias
    IntentType,
    # Action verbs for multi-intent detection
    ACTION_VERBS,
)

# Re-export from pre_gates (for direct access if needed)
from src.graph.intent.pre_gates import (
    _detect_decision_type_hint,
    DECISION_TYPE_KEYWORDS,
)

__all__ = [
    # Main API
    "classify_intent",
    "classify_intent_with_context",
    "classify_intent_v2",
    "intent_router_node",
    "get_intent_classifier",
    "should_use_multi_intent_classification",
    "run_pre_gates",
    # Legacy
    "IntentType",
    # Constants
    "ACTION_VERBS",
    "DECISION_TYPE_KEYWORDS",
    # Internal (for testing/debugging)
    "_detect_decision_type_hint",
]
