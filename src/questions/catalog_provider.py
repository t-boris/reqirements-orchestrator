"""CatalogProvider - QuestionProvider implementation for WorkItemDraft.

Wraps existing QuestionCatalog templates and generators.
Targets WorkItemDraft fields with deterministic questions.
"""
from typing import Any, Optional

from src.questions.catalog import QuestionCatalog
from src.schemas.question import QuestionTask


class CatalogProvider:
    """QuestionProvider for structured work items.

    Uses QuestionCatalog templates for deterministic questions:
    - CONFIRM_SCOPE: parent selection, draft scope, generation mode
    - RESOLVE_CONFLICT: field conflicts between local/remote
    - COLLECT_FIELD: LLM-generated for specific fields

    Target: WorkItemDraft
    """

    def __init__(self, llm: Optional[Any] = None):
        """Initialize with optional LLM for field collection.

        Args:
            llm: LLM client for COLLECT_FIELD questions
        """
        self._llm = llm

    def get_target_type(self) -> str:
        """Return target state type."""
        return "workitem"

    async def generate_question(
        self,
        context: dict[str, Any],
        missing_fields: list[str],
    ) -> QuestionTask | None:
        """Generate next question for WorkItemDraft.

        Priority order:
        1. Scope confirmation (if parent ambiguous)
        2. Conflict resolution (if conflicts exist)
        3. Field collection (for missing required fields)

        Args:
            context: Current WorkItemDraft as dict
            missing_fields: Fields that need values

        Returns:
            QuestionTask or None if no questions needed
        """
        # Check for scope questions first
        if context.get("needs_scope_confirmation"):
            template = context.get("scope_template", "generation_mode")
            return QuestionCatalog.confirm_scope(context, template)

        # Check for conflicts
        conflicts = context.get("conflicts", [])
        if conflicts:
            conflict = conflicts[0]
            return QuestionCatalog.resolve_conflict(
                field=conflict["field"],
                local_value=conflict["local"],
                remote_value=conflict["remote"],
            )

        # Collect missing fields
        required_fields = ["title", "problem"]
        for field in required_fields:
            if field in missing_fields and not context.get(field):
                return await QuestionCatalog.collect_field(
                    field=field,
                    draft_context=context,
                    llm=self._llm,
                )

        # Optional fields with lower priority
        optional_fields = ["acceptance_criteria", "proposed_solution"]
        for field in optional_fields:
            if field in missing_fields and not context.get(field):
                return await QuestionCatalog.collect_field(
                    field=field,
                    draft_context=context,
                    llm=self._llm,
                )

        return None  # No questions needed

    async def generate_fallback_question(
        self,
        context_description: str,
    ) -> QuestionTask:
        """Generate freeform question when no template fits.

        Args:
            context_description: What we need to clarify

        Returns:
            QuestionTask with LLM-generated question
        """
        return await QuestionCatalog.ask_user(context_description, self._llm)
