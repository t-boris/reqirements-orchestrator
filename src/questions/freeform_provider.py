"""FreeformProvider - QuestionProvider implementation for ReviewState.

Generates structured questions via LLM for architecture review.
Even freeform questions return structured ReviewQuestion format.
"""
import json
import logging
from typing import Any, Optional

from src.schemas.question import QuestionOption, QuestionTask, QuestionType
from src.schemas.review_state import OpenQuestion

logger = logging.getLogger(__name__)


QUESTION_GENERATION_PROMPT = '''You are an architecture reviewer helping clarify a design.

Current review context:
Topic: {topic}
Assumptions so far: {assumptions}
Constraints identified: {constraints}
Risks identified: {risks}

Areas needing clarification: {missing_fields}

Generate ONE focused question to clarify the most important gap.

Return JSON:
{{
  "goal": "what this question resolves (e.g., 'disambiguate transport layer')",
  "question": "the actual question to ask",
  "expected_answer_type": "choice|text|number",
  "options": ["option1", "option2"] or null if text/number,
  "maps_to": "which field this answer updates (assumptions|constraints|risks)"
}}

JSON:'''


class FreeformProvider:
    """QuestionProvider for architecture review.

    Uses LLM to generate contextual questions, but outputs
    structured ReviewQuestion format for consistent UX.

    Target: ReviewState
    """

    def __init__(self, llm: Optional[Any] = None):
        """Initialize with LLM client.

        Args:
            llm: LLM client for question generation
        """
        self._llm = llm

    def get_target_type(self) -> str:
        """Return target state type."""
        return "review"

    async def generate_question(
        self,
        context: dict[str, Any],
        missing_fields: list[str],
    ) -> QuestionTask | None:
        """Generate next question for ReviewState.

        Uses LLM to determine the most important clarification needed,
        then formats as structured QuestionTask.

        Args:
            context: Current ReviewState as dict
            missing_fields: Areas that need clarification

        Returns:
            QuestionTask or None if review is complete
        """
        if not missing_fields:
            return None

        llm = self._llm
        if llm is None:
            from src.llm import get_llm
            llm = get_llm()

        # Format context for prompt
        prompt = QUESTION_GENERATION_PROMPT.format(
            topic=context.get("topic", "Unknown"),
            assumptions=self._format_list(context.get("assumptions", [])),
            constraints=self._format_list(context.get("constraints", [])),
            risks=self._format_list(context.get("risks", [])),
            missing_fields=", ".join(missing_fields),
        )

        response = await llm.chat(prompt)
        question_data = self._parse_llm_response(response)

        if not question_data:
            # Fallback to generic question
            return self._create_fallback_question(missing_fields[0])

        return self._create_question_task(question_data)

    def _format_list(self, items: list) -> str:
        """Format list of items for prompt."""
        if not items:
            return "None yet"
        # Handle both dict and model objects
        formatted = []
        for item in items[:5]:  # Limit to 5 for prompt size
            if isinstance(item, dict):
                formatted.append(item.get("statement") or item.get("description", str(item)))
            elif hasattr(item, "statement"):
                formatted.append(item.statement)
            elif hasattr(item, "description"):
                formatted.append(item.description)
            else:
                formatted.append(str(item))
        return "; ".join(formatted)

    def _parse_llm_response(self, response: str) -> Optional[dict]:
        """Parse LLM JSON response."""
        try:
            # Strip markdown if present
            text = response.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    def _create_question_task(self, data: dict) -> QuestionTask:
        """Create QuestionTask from parsed LLM response."""
        options = None
        if data.get("expected_answer_type") == "choice" and data.get("options"):
            options = [
                QuestionOption(
                    option_id=f"opt_{i}",
                    label=opt,
                    value=opt,
                )
                for i, opt in enumerate(data["options"])
            ]

        return QuestionTask(
            question_type=QuestionType.ASK_USER,  # Freeform uses ASK_USER type
            question_text=data.get("question", "Could you clarify?"),
            target_field=data.get("maps_to"),
            options=options,
        )

    def _create_fallback_question(self, field: str) -> QuestionTask:
        """Create fallback question when LLM fails."""
        field_questions = {
            "assumptions": "What assumptions are we making about the system design?",
            "constraints": "Are there any constraints we should consider?",
            "risks": "What risks do you see with this approach?",
        }
        question = field_questions.get(field, f"Could you tell me more about {field}?")

        return QuestionTask(
            question_type=QuestionType.ASK_USER,
            question_text=question,
            target_field=field,
            options=None,
        )

    async def generate_from_open_questions(
        self,
        open_questions: list[OpenQuestion],
    ) -> QuestionTask | None:
        """Convert existing OpenQuestion to QuestionTask.

        When user says "ask me your questions", we convert stored
        OpenQuestion objects to QuestionTask format.

        Args:
            open_questions: List of unanswered OpenQuestion from ReviewState

        Returns:
            QuestionTask for the highest priority unanswered question
        """
        unanswered = [q for q in open_questions if q.answer is None]
        if not unanswered:
            return None

        q = unanswered[0]

        options = None
        if q.expected_answer_type == "choice" and q.options:
            options = [
                QuestionOption(
                    option_id=f"opt_{i}",
                    label=opt,
                    value=opt,
                )
                for i, opt in enumerate(q.options)
            ]

        return QuestionTask(
            question_id=q.id,  # Preserve original ID
            question_type=QuestionType.ASK_USER,
            question_text=q.question,
            target_field=q.maps_to,
            options=options,
        )
