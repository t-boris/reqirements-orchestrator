"""AnswerMapper for processing user responses in Question Engine.

Provides deterministic mapping for button clicks and LLM-based parsing
for text replies. Returns StatePatch instances for applying answers to state.
"""

import json
from typing import Any, Optional

from src.schemas.question import QuestionTask
from src.schemas.state_patch import AnswerSource, StatePatch, create_button_patch


class ButtonAnswerMapper:
    """Deterministic answer mapping from button clicks.

    Button action_ids encode field and value:
    - action_id = "question_{question_id}_{option_id}"
    - value = "{question_id}:{option_id}:{encoded_value}"

    No LLM involved - pure deterministic mapping.
    """

    @staticmethod
    def parse_action_id(action_id: str) -> tuple[str, str]:
        """Parse action_id to extract question_id and option_id.

        Args:
            action_id: "question_{question_id}_{option_id}"

        Returns:
            (question_id, option_id) tuple

        Raises:
            ValueError: If action_id format is invalid
        """
        parts = action_id.split("_", 2)
        if len(parts) < 3 or parts[0] != "question":
            raise ValueError(f"Invalid action_id format: {action_id}")
        return parts[1], parts[2]

    @staticmethod
    def parse_value(value: str) -> tuple[str, str, str]:
        """Parse button value to extract question_id, option_id, encoded_value.

        Args:
            value: "{question_id}:{option_id}:{encoded_value}"

        Returns:
            (question_id, option_id, encoded_value) tuple

        Raises:
            ValueError: If value format is invalid
        """
        parts = value.split(":", 2)
        if len(parts) < 3:
            raise ValueError(f"Invalid value format: {value}")
        return parts[0], parts[1], parts[2]

    @staticmethod
    def map_click(
        action_id: str,
        value: str,
        question_task: QuestionTask,
    ) -> StatePatch:
        """Map button click to StatePatch.

        Args:
            action_id: Button action ID
            value: Button value
            question_task: The question being answered

        Returns:
            StatePatch with deterministic mapping (confidence=1.0)
        """
        question_id, option_id, encoded_value = ButtonAnswerMapper.parse_value(value)

        # Find matching option
        matched_option = None
        if question_task.options:
            for opt in question_task.options:
                if opt.option_id == option_id:
                    matched_option = opt
                    break

        if matched_option:
            actual_value = matched_option.value
        else:
            # Fallback to encoded value
            actual_value = encoded_value

        return create_button_patch(
            field=question_task.target_field or "response",
            value=actual_value,
            question_id=question_id,
        )


class TextAnswerMapper:
    """LLM-based answer mapping from text replies.

    Parses user text against expected field schema.
    Returns confidence score - below threshold triggers clarification.
    """

    PARSE_PROMPT = '''Parse the user's text response for the "{field}" field.

Expected field: {field}
{schema_hint}

User's text:
"{text}"

Return JSON:
{{
  "value": <extracted value or null if unclear>,
  "confidence": 0.0-1.0,
  "needs_clarification": true/false,
  "clarification_reason": "why clarification needed (if any)"
}}

JSON:'''

    FIELD_SCHEMAS: dict[str, str] = {
        "scope": "Options: SINGLE, EPICS_ONLY, FULL_PLAN",
        "generation_mode": "Options: SUGGEST_WORKSTREAMS, USER_TITLES, FROM_DECISIONS",
        "acceptance_criteria": "List of testable conditions (strings)",
        "title": "Short, action-oriented title (string)",
        "problem": "Problem statement (string)",
        "proposed_solution": "Solution description (string)",
    }

    @staticmethod
    async def map_text(
        text: str,
        expected_field: str,
        question_task: QuestionTask,
        llm=None,
    ) -> StatePatch:
        """Map text reply to StatePatch using LLM.

        Args:
            text: User's text reply
            expected_field: Field we're trying to fill
            question_task: The question being answered
            llm: LLM instance (defaults to get_llm())

        Returns:
            StatePatch with LLM-derived confidence
        """
        if llm is None:
            from src.llm import get_llm
            llm = get_llm()

        schema_hint = TextAnswerMapper.FIELD_SCHEMAS.get(expected_field, "Free-form text")
        prompt = TextAnswerMapper.PARSE_PROMPT.format(
            field=expected_field,
            schema_hint=schema_hint,
            text=text,
        )

        response = await llm.chat(prompt)
        result = TextAnswerMapper._parse_llm_response(response)

        return StatePatch(
            field=expected_field,
            value=result.get("value"),
            source=AnswerSource.TEXT,
            confidence=float(result.get("confidence", 0.5)),
            question_id=question_task.question_id,
            raw_input=text,
        )

    @staticmethod
    def _parse_llm_response(response: str) -> dict:
        """Parse LLM JSON response with fallback.

        Args:
            response: Raw LLM response string

        Returns:
            Parsed dict with value, confidence, needs_clarification
        """
        try:
            # Strip markdown if present
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            return json.loads(response.strip())
        except json.JSONDecodeError:
            return {"value": None, "confidence": 0.3, "needs_clarification": True}


class AnswerMapper:
    """Unified answer mapper facade.

    Routes to appropriate mapper based on input type:
    - Button clicks -> ButtonAnswerMapper (deterministic)
    - Text replies -> TextAnswerMapper (LLM-parsed)
    """

    @staticmethod
    def map_button_click(
        action_id: str,
        value: str,
        question_task: QuestionTask,
    ) -> StatePatch:
        """Map button click to patch (deterministic).

        Args:
            action_id: Button action ID
            value: Button value
            question_task: The question being answered

        Returns:
            StatePatch with confidence=1.0
        """
        return ButtonAnswerMapper.map_click(action_id, value, question_task)

    @staticmethod
    async def map_text_reply(
        text: str,
        question_task: QuestionTask,
        llm=None,
    ) -> StatePatch:
        """Map text reply to patch (LLM-parsed).

        Args:
            text: User's text reply
            question_task: The question being answered
            llm: Optional LLM instance

        Returns:
            StatePatch with LLM-derived confidence
        """
        return await TextAnswerMapper.map_text(
            text,
            question_task.target_field or "response",
            question_task,
            llm,
        )


def encode_button_action_id(question_id: str, option_id: str) -> str:
    """Create action_id for button.

    Args:
        question_id: ID of the question
        option_id: ID of the option

    Returns:
        Formatted action_id string
    """
    return f"question_{question_id}_{option_id}"


def encode_button_value(question_id: str, option_id: str, value: Any) -> str:
    """Create value string for button.

    Args:
        question_id: ID of the question
        option_id: ID of the option
        value: The value to encode

    Returns:
        Formatted value string
    """
    encoded = str(value) if value is not None else "null"
    return f"{question_id}:{option_id}:{encoded}"
