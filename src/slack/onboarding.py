"""Onboarding and contextual hint system.

MARO's onboarding personality: Quiet. Observant. Helpful only when needed.
Teaches by doing, not by lecturing.
"""
import logging
from enum import Enum
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class HintType(str, Enum):
    """Types of contextual hints."""
    GREETING = "greeting"           # User says hi/hello
    VAGUE_IDEA = "vague_idea"       # User mentions something vague
    PERSPECTIVE_NEEDED = "perspective"  # User asks "what do you think"
    CONFUSED = "confused"           # User seems lost
    NONE = "none"                   # No hint needed


class HintResult(BaseModel):
    """Result of hint classification."""
    hint_type: HintType
    hint_message: str = ""
    show_buttons: bool = False
    buttons: list[dict] = []


# Predefined hint responses (from 12-CONTEXT.md)
HINT_RESPONSES = {
    HintType.GREETING: HintResult(
        hint_type=HintType.GREETING,
        hint_message="Hi. I help turn discussions into Jira tickets. Tell me about a feature, bug, or change you want to work on.",
    ),
    HintType.VAGUE_IDEA: HintResult(
        hint_type=HintType.VAGUE_IDEA,
        hint_message="Do you want to create a Jira ticket for that, or just discuss it for now?",
    ),
    HintType.PERSPECTIVE_NEEDED: HintResult(
        hint_type=HintType.PERSPECTIVE_NEEDED,
        hint_message="I can review this as requirements, architecture, or security. Which perspective do you want?",
        show_buttons=True,
        buttons=[
            {"text": "PM", "value": "pm"},
            {"text": "Architect", "value": "architect"},
            {"text": "Security", "value": "security"},
        ],
    ),
    HintType.CONFUSED: HintResult(
        hint_type=HintType.CONFUSED,
        hint_message="Quick tip: you can say things like 'Create a Jira Story for...' or 'Draft requirements for...'",
    ),
}


async def classify_hesitation(message: str, is_first_message: bool = True) -> HintResult:
    """Classify if user message indicates hesitation or need for guidance.

    Uses LLM to understand intent, not just pattern matching.

    Args:
        message: User's message text
        is_first_message: Whether this is first interaction in thread

    Returns:
        HintResult with appropriate hint type and message
    """
    # Quick pattern checks for obvious cases
    message_lower = message.lower().strip()

    # Greeting patterns (simple)
    greeting_words = ["hi", "hello", "hey", "yo", "sup", "morning", "afternoon", "evening"]
    if message_lower in greeting_words or message_lower.rstrip("!") in greeting_words:
        return HINT_RESPONSES[HintType.GREETING]

    # Perspective question pattern
    perspective_patterns = ["what do you think", "your thoughts", "your opinion", "feedback on this"]
    if any(p in message_lower for p in perspective_patterns):
        return HINT_RESPONSES[HintType.PERSPECTIVE_NEEDED]

    # Use LLM for more nuanced classification
    try:
        from src.llm import get_llm

        llm = get_llm()

        prompt = f"""Analyze this message from a user talking to a Jira ticket assistant. Classify the user's intent.

User message: "{message}"

Classify into ONE of these categories:
- VAGUE_IDEA: User mentions something they want but it's unclear if they want a ticket or just discussing (e.g., "we should improve notifications", "the login is slow")
- CONFUSED: User seems lost or uncertain what to do (e.g., "um...", "not sure how this works", random text)
- NONE: User has a clear request or is providing concrete information

Respond with ONLY the category name (VAGUE_IDEA, CONFUSED, or NONE).
If in doubt, respond NONE."""

        result = await llm.chat(prompt)
        classification = result.strip().upper()

        if classification == "VAGUE_IDEA":
            return HINT_RESPONSES[HintType.VAGUE_IDEA]
        elif classification == "CONFUSED":
            return HINT_RESPONSES[HintType.CONFUSED]
        else:
            return HintResult(hint_type=HintType.NONE)

    except Exception as e:
        logger.warning(f"Hesitation classification failed: {e}")
        return HintResult(hint_type=HintType.NONE)


def get_intro_message() -> str:
    """Get the intro message for first interaction.

    Used when user's first message results in empty draft.
    """
    return HINT_RESPONSES[HintType.GREETING].hint_message
