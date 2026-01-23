"""Input classifier - classify user input type for routing decisions.

Distinguishes between:
- CHOICE: Structural decision requiring immediate action
- OPINION: Preference expression, discussion continues
- QUESTION: User asking something, needs answer
- ANSWER: Direct response to bot's question
- UNCLEAR: Cannot determine intent

Phase 28.5: User Input Classification (R3, R7, R10)
"""
import json
import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.llm import get_llm

logger = logging.getLogger(__name__)


class InputClass(str, Enum):
    """Classification of user input type."""

    CHOICE = "choice"  # Structural decision -> ACTION
    OPINION = "opinion"  # Preference -> DISCUSSION
    QUESTION = "question"  # User asking -> ANSWER
    ANSWER = "answer"  # Response to bot question
    UNCLEAR = "unclear"  # Cannot determine


class InputClassification(BaseModel):
    """Result of classifying user input."""

    input_class: InputClass
    confidence: float = Field(ge=0.0, le=1.0)
    structural_action: Optional[str] = None  # For CHOICE: split_to_plan, change_scope, etc.
    answered_field: Optional[str] = None  # For ANSWER: which field was answered
    reason: str = ""


# Structural actions that can be detected from CHOICE inputs
STRUCTURAL_ACTIONS = {
    "split_to_plan": [
        "split",
        "break down",
        "breakdown",
        "decompose",
        "break up",
        "divide",
    ],
    "change_scope": [
        "only epic",
        "epics only",
        "just epic",
        "epic level",
        "full plan",
        "with stories",
        "complete breakdown",
    ],
    "add_items": ["add", "include", "also need"],
    "remove_items": ["remove", "delete", "drop", "exclude"],
    "merge_items": ["merge", "combine", "consolidate"],
    "elevate_to_epic": ["make it an epic", "elevate", "promote to epic"],
}


CLASSIFICATION_PROMPT = '''Classify the user's message into one of these categories:

1. CHOICE - User is making a structural decision that requires immediate action
   Signals: imperative commands ("split it", "only epics", "merge these", "add X")
   Examples: "Split this into epics", "Only epics", "Add a story for auth"

2. OPINION - User is expressing a preference without commanding action
   Signals: hedging ("I think", "maybe", "could"), conditionals, suggestions
   Examples: "I think we might need auth", "Maybe we should consider...", "Could be split"

3. QUESTION - User is asking a question, needs the bot to answer
   Signals: interrogative form ("should we?", "is it?", "do you think?", "what about?")
   Examples: "Should we split this?", "Is one epic enough?", "What do you think?"

4. ANSWER - User is directly responding to a pending question from the bot
   Signals: appears to answer {pending_questions_text}
   Examples: Direct responses to questions, "yes", "no", confirmations

5. UNCLEAR - Cannot confidently determine the intent

{pending_context}

User message:
"{message}"

Return JSON:
{{
  "input_class": "choice|opinion|question|answer|unclear",
  "confidence": 0.0-1.0,
  "structural_action": "action_name or null (only for CHOICE)",
  "answered_field": "field_name or null (only for ANSWER)",
  "reason": "brief explanation"
}}

For CHOICE, structural_action should be one of: split_to_plan, change_scope, add_items, remove_items, merge_items, elevate_to_epic, or null if unclear.

JSON response:'''


def _detect_structural_action(message: str) -> Optional[str]:
    """Detect structural action from message using keyword matching.

    Returns action name if detected, None otherwise.
    """
    message_lower = message.lower()

    for action, keywords in STRUCTURAL_ACTIONS.items():
        for keyword in keywords:
            if keyword in message_lower:
                return action

    return None


async def classify_input(
    message: str,
    pending_questions: Optional[list[str]] = None,
) -> InputClassification:
    """Classify user input type for routing decisions.

    Args:
        message: User's message text
        pending_questions: List of questions the bot asked (if any)

    Returns:
        InputClassification with type, confidence, and optional action/field
    """
    if not message or not message.strip():
        return InputClassification(
            input_class=InputClass.UNCLEAR,
            confidence=0.0,
            reason="Empty message",
        )

    # Build pending questions context
    pending_questions_text = "No pending questions"
    pending_context = ""
    if pending_questions:
        pending_questions_text = ", ".join(f'"{q}"' for q in pending_questions)
        pending_context = f"\nPending questions the bot asked:\n{pending_questions_text}\n"

    prompt = CLASSIFICATION_PROMPT.format(
        message=message,
        pending_questions_text=pending_questions_text,
        pending_context=pending_context,
    )

    try:
        llm = get_llm()
        response_text = await llm.chat(prompt)
        response_text = response_text.strip()

        # Parse JSON response
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        result = json.loads(response_text) if response_text else {}

        input_class_str = result.get("input_class", "unclear").lower()
        try:
            input_class = InputClass(input_class_str)
        except ValueError:
            input_class = InputClass.UNCLEAR

        # For CHOICE, try to detect structural action if LLM didn't provide one
        structural_action = result.get("structural_action")
        if input_class == InputClass.CHOICE and not structural_action:
            structural_action = _detect_structural_action(message)

        classification = InputClassification(
            input_class=input_class,
            confidence=float(result.get("confidence", 0.5)),
            structural_action=structural_action,
            answered_field=result.get("answered_field"),
            reason=result.get("reason", ""),
        )

        logger.info(
            "Classified user input",
            extra={
                "input_class": input_class.value,
                "confidence": classification.confidence,
                "structural_action": structural_action,
                "message_preview": message[:50],
            },
        )

        return classification

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse classification response: {e}")
        # Fallback to keyword detection
        structural_action = _detect_structural_action(message)
        if structural_action:
            return InputClassification(
                input_class=InputClass.CHOICE,
                confidence=0.6,
                structural_action=structural_action,
                reason="Keyword detection fallback",
            )
        return InputClassification(
            input_class=InputClass.UNCLEAR,
            confidence=0.3,
            reason=f"Failed to parse LLM response: {e}",
        )
    except Exception as e:
        logger.error(f"Input classification failed: {e}")
        return InputClassification(
            input_class=InputClass.UNCLEAR,
            confidence=0.0,
            reason=f"Classification error: {e}",
        )


def normalize_question_key(question: str) -> str:
    """Normalize question text to a consistent key for tracking.

    Maps question text to field names for consistent tracking.

    Examples:
        "What are the acceptance criteria?" -> "acceptance_criteria"
        "What problem are we solving?" -> "problem"
        "Would you like epics or full plan?" -> "scope_decision"

    Args:
        question: Full question text

    Returns:
        Normalized key string
    """
    question_lower = question.lower()

    # Direct field mappings
    field_mappings = {
        "acceptance criteria": "acceptance_criteria",
        "problem": "problem",
        "title": "title",
        "proposed solution": "proposed_solution",
        "solution": "proposed_solution",
        "dependencies": "dependencies",
        "risks": "risks",
        "constraints": "constraints",
    }

    for pattern, key in field_mappings.items():
        if pattern in question_lower:
            return key

    # Scope-related questions
    scope_patterns = [
        "epic or",
        "epics or",
        "full plan",
        "scope",
        "breakdown",
        "decompose",
    ]
    for pattern in scope_patterns:
        if pattern in question_lower:
            return "scope_decision"

    # Decomposition questions
    decomp_patterns = [
        "break down",
        "split",
        "items should",
        "stories",
    ]
    for pattern in decomp_patterns:
        if pattern in question_lower:
            return "decomposition"

    # Fallback: create key from first few words
    words = question_lower.split()[:3]
    return "_".join(w for w in words if w.isalnum())[:30]
