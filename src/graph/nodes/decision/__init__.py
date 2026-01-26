"""Decision package - routes draft to next action.

Re-exports main entry points:
- decision_node: Main graph node for decision making
- DecisionResult: Result model for decision outcomes
- get_decision_action: Helper for graph conditional edges
"""
from src.graph.nodes.decision.node import decision_node, get_decision_action
from src.graph.nodes.decision.models import DecisionResult

# Also expose internal helpers for backward compatibility
from src.graph.nodes.decision.questions import (
    prioritize_issues,
    batch_questions,
    get_lifecycle_questions as _get_lifecycle_questions,
)
from src.graph.nodes.decision.duplicates import search_for_duplicates as _search_for_duplicates
from src.graph.nodes.decision.refinement import build_refinement_prompt as _build_refinement_prompt

__all__ = [
    "decision_node",
    "DecisionResult",
    "get_decision_action",
    # Internal helpers
    "prioritize_issues",
    "batch_questions",
    "_get_lifecycle_questions",
    "_search_for_duplicates",
    "_build_refinement_prompt",
]
