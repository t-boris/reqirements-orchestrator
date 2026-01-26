"""QuestionEngine - Unified interface for question-driven conversations.

One engine, three providers:
- CatalogProvider for WorkItemDraft (tickets)
- FreeformProvider for ReviewState (architecture review)
- TriageProvider for context gap clarification (triage)

Same UX (buttons, budget, throttle) for all paths.
"""
import logging
from typing import Any, Literal, Optional

from src.questions.answer_mapper import AnswerMapper
from src.questions.budget_tracker import BudgetTracker
from src.questions.catalog_provider import CatalogProvider
from src.questions.freeform_provider import FreeformProvider
from src.questions.provider import ProviderType
from src.questions.triage_provider import TriageProvider
from src.schemas.question import QuestionTask
from src.schemas.state_patch import StatePatch
from src.schemas.triage import TriageGap

logger = logging.getLogger(__name__)


class QuestionEngine:
    """Unified question engine for all conversation types.

    Handles:
    - When to ask (budget check, missing fields)
    - How to display (via provider-generated QuestionTask)
    - How to accept (button → deterministic, text → LLM parse)
    - How to map (to WorkItemDraft or ReviewState)
    - How to throttle (budget tracker)
    """

    def __init__(
        self,
        budget_tracker: BudgetTracker,
        llm: Optional[Any] = None,
    ):
        """Initialize QuestionEngine.

        Args:
            budget_tracker: BudgetTracker for throttling
            llm: Optional LLM client for question generation
        """
        self._budget_tracker = budget_tracker
        self._catalog_provider = CatalogProvider(llm)
        self._freeform_provider = FreeformProvider(llm)
        self._triage_provider = TriageProvider()
        self._llm = llm

    async def should_ask(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Check if we should ask another question (budget not exhausted).

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            True if under budget
        """
        return await self._budget_tracker.can_ask(channel_id, thread_ts)

    async def generate_question(
        self,
        provider_type: ProviderType,
        context: dict[str, Any],
        missing_fields: list[str],
    ) -> QuestionTask | None:
        """Generate next question using appropriate provider.

        Args:
            provider_type: CATALOG or FREEFORM
            context: Current state (WorkItemDraft or ReviewState)
            missing_fields: Fields that need values

        Returns:
            QuestionTask or None if complete
        """
        provider = (
            self._catalog_provider
            if provider_type == ProviderType.CATALOG
            else self._freeform_provider
        )
        return await provider.generate_question(context, missing_fields)

    async def record_question(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> int:
        """Record that a question was asked.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            New unanswered count
        """
        return await self._budget_tracker.record_question_asked(channel_id, thread_ts)

    async def process_button_answer(
        self,
        action_id: str,
        value: str,
        question_task: QuestionTask,
    ) -> StatePatch:
        """Process button click answer (deterministic).

        Args:
            action_id: Button action ID
            value: Button value
            question_task: The question being answered

        Returns:
            StatePatch with confidence=1.0
        """
        return AnswerMapper.map_button_click(action_id, value, question_task)

    async def process_text_answer(
        self,
        text: str,
        question_task: QuestionTask,
        target_type: Literal["workitem", "review"] = "workitem",
    ) -> StatePatch:
        """Process text reply answer (LLM-parsed).

        Args:
            text: User's text reply
            question_task: The question being answered
            target_type: "workitem" or "review"

        Returns:
            StatePatch with LLM-derived confidence
        """
        return await AnswerMapper.map_text_reply(
            text, question_task, target_type, self._llm
        )

    async def record_answer(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> None:
        """Record that user answered (resets budget).

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
        """
        await self._budget_tracker.record_answer_received(channel_id, thread_ts)

    async def is_budget_exhausted(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> bool:
        """Check if budget is exhausted.

        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp

        Returns:
            True if at or over budget limit
        """
        return await self._budget_tracker.is_exhausted(channel_id, thread_ts)

    def get_freeform_provider(self) -> FreeformProvider:
        """Get FreeformProvider for direct access.

        Useful for generate_from_open_questions.
        """
        return self._freeform_provider

    async def generate_triage_question(
        self,
        gaps: set[TriageGap],
        context: dict[str, Any],
    ) -> QuestionTask | None:
        """Generate triage question for context gaps.

        Args:
            gaps: Set of TriageGap from triage gate
            context: Current state context

        Returns:
            QuestionTask for highest priority gap, or None if no gaps
        """
        return self._triage_provider.get_next_question(gaps, context)
