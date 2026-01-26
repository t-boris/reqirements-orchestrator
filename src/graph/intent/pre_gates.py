"""Stage 0: Pre-gate logic for intent classification.

Pre-gates are deterministic checks that run BEFORE LLM classification.
They detect decision type hints from keywords in user messages.

This module is part of the modularized intent package (Phase 42).
"""
from typing import Optional


# =============================================================================
# Decision type hints based on keywords (used after LLM classification)
# =============================================================================

# Decision type hints based on keywords
# Maps from hint type to keywords that indicate it
DECISION_TYPE_KEYWORDS: dict[str, list[str]] = {
    "arch": [
        "architecture", "tech stack", "framework", "library", "database",
        "api design", "microservice", "monolith", "stack", "technology",
        "infrastructure", "platform", "tool", "service",
    ],
    "scope": [
        "scope", "boundary", "include", "exclude", "out of scope", "in scope",
        "mvp", "phase 1", "first version", "later", "future",
    ],
    "constraint": [
        "constraint", "limitation", "must not", "cannot", "required to",
        "must have", "non-negotiable", "hard requirement", "compliance",
    ],
    "priority": [
        "priority", "p0", "p1", "p2", "first", "before", "after", "order",
        "blocker", "critical", "urgent", "important",
    ],
    "structure": [
        "epic", "story", "breakdown", "split", "decompose", "structure",
        "parent", "child", "hierarchy",
    ],
    "process": [
        "process", "workflow", "procedure", "how we", "when we",
        "review process", "approval", "deploy", "release",
    ],
}


def _detect_decision_type_hint(message: str) -> Optional[str]:
    """Detect decision type from keywords in message.

    Returns the decision type hint (arch, scope, etc.) if keywords match,
    None otherwise.
    """
    message_lower = message.lower()

    for type_hint, keywords in DECISION_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                return type_hint

    return None
