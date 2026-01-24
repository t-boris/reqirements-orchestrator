"""QuestionProvider interface for the unified Question Engine.

Phase 37: Unified Question Engine

This module defines the abstract interface for question providers.
Two implementations:
- CatalogProvider: deterministic questions for WorkItemDraft
- FreeformProvider: LLM-generated questions for ReviewState
"""
from enum import Enum
from typing import Any, Protocol

from src.schemas.question import QuestionTask


class ProviderType(str, Enum):
    """Type of question provider.

    Determines which provider to use for generating questions:
    - CATALOG: Template-based questions for WorkItemDraft (tickets)
    - FREEFORM: LLM-generated questions for ReviewState (architecture review)
    """
    CATALOG = "catalog"      # For WorkItemDraft
    FREEFORM = "freeform"    # For ReviewState


class QuestionProvider(Protocol):
    """Abstract interface for question providers.

    Two implementations:
    - CatalogProvider: deterministic questions for WorkItemDraft
    - FreeformProvider: LLM-generated questions for ReviewState
    """

    async def generate_question(
        self,
        context: dict[str, Any],
        missing_fields: list[str],
    ) -> QuestionTask | None:
        """Generate next question based on context and gaps.

        Args:
            context: Current state (WorkItemDraft or ReviewState)
            missing_fields: Fields that need values

        Returns:
            QuestionTask if question needed, None if complete
        """
        ...

    def get_target_type(self) -> str:
        """Return target state type: 'workitem' or 'review'."""
        ...
