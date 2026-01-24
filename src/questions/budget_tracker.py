"""BudgetTracker for enforcing question limits in Question Engine.

Tracks and enforces the question budget per conversation thread.
After budget is exhausted, the system should show a partial preview
instead of continuing to ask questions.
"""

from enum import Enum

from src.db.conversation_mode_store import ConversationModeStore
from src.schemas.conversation_mode import QUESTION_BUDGET


class BudgetExhaustedAction(str, Enum):
    """User choices when budget is exhausted.

    When the system has asked QUESTION_BUDGET unanswered questions,
    it presents these options to the user.
    """

    PROCEED_WITH_GAPS = "proceed_with_gaps"  # Continue with incomplete info
    WAIT_FOR_INPUT = "wait_for_input"  # Stay in thread, wait for user
    CANCEL = "cancel"  # Cancel the operation


class BudgetTracker:
    """Track and enforce question budget per thread.

    Rules:
    1. Max QUESTION_BUDGET (2) unanswered questions in a row
    2. New user message resets budget
    3. After budget exhausted -> partial preview mode
    """

    def __init__(self, store: ConversationModeStore) -> None:
        """Initialize BudgetTracker with a store.

        Args:
            store: ConversationModeStore for state persistence
        """
        self._store = store

    async def can_ask(self, channel_id: str, thread_ts: str) -> bool:
        """Check if we can ask another question.

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp

        Returns:
            True if under budget, False if exhausted
        """
        state = await self._store.get_or_create(channel_id, thread_ts)
        return state.unanswered_questions < QUESTION_BUDGET

    async def record_question_asked(self, channel_id: str, thread_ts: str) -> int:
        """Record that a question was asked.

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp

        Returns:
            New unanswered count
        """
        return await self._store.increment_unanswered(channel_id, thread_ts)

    async def record_answer_received(self, channel_id: str, thread_ts: str) -> None:
        """Record that user answered (resets budget).

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp
        """
        await self._store.reset_unanswered(channel_id, thread_ts)

    async def get_remaining(self, channel_id: str, thread_ts: str) -> int:
        """Get remaining questions before budget exhausted.

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp

        Returns:
            Number of questions remaining (0 to QUESTION_BUDGET)
        """
        state = await self._store.get_or_create(channel_id, thread_ts)
        return max(0, QUESTION_BUDGET - state.unanswered_questions)

    async def is_exhausted(self, channel_id: str, thread_ts: str) -> bool:
        """Check if budget is exhausted (should show partial preview).

        Args:
            channel_id: Slack channel ID
            thread_ts: Slack thread timestamp

        Returns:
            True if at or over budget limit
        """
        return not await self.can_ask(channel_id, thread_ts)
