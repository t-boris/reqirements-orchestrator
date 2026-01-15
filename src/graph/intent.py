"""Intent Router for classifying user messages.

Classifies user messages into three flows:
- TICKET: User wants to create a Jira ticket
- REVIEW: User wants analysis/feedback without Jira operations
- DISCUSSION: Casual greeting, simple question, no action needed

Pattern matching is applied first for explicit overrides.
LLM classification is used only for ambiguous cases.
"""
import logging
import re
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """Types of user intent."""
    TICKET = "TICKET"       # Create a Jira ticket
    REVIEW = "REVIEW"       # Analysis/feedback without Jira
    DISCUSSION = "DISCUSSION"  # Casual greeting, simple question


class IntentResult(BaseModel):
    """Result of intent classification."""
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    persona_hint: Optional[Literal["pm", "architect", "security"]] = None
    topic: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)


# Explicit override patterns (checked BEFORE LLM)
# These force specific intents with confidence=1.0

# NEGATION PATTERNS - checked FIRST (highest priority)
# These override positive TICKET patterns when user explicitly says "don't create ticket"
NEGATION_PATTERNS = [
    (r"\bdon'?t\s+create\s+(?:a\s+)?ticket\b", "pattern: don't create ticket"),
    (r"\bno\s+ticket\b", "pattern: no ticket"),
    (r"\bwithout\s+(?:a\s+)?(?:jira\s+)?ticket\b", "pattern: without ticket"),
    (r"\bjust\s+(?:review|analyze|discuss)\b", "pattern: just review"),
]

TICKET_PATTERNS = [
    # Explicit ticket creation requests
    (r"\bcreate\s+(?:a\s+)?ticket\b", "pattern: create ticket"),
    (r"\bdraft\s+(?:a\s+)?ticket\b", "pattern: draft ticket"),
    (r"\bjira\s+(?:story|ticket|issue|bug|task)\b", "pattern: jira story/ticket"),
    (r"\bmake\s+(?:a\s+)?(?:jira\s+)?ticket\b", "pattern: make ticket"),
    (r"\bwrite\s+(?:a\s+)?ticket\b", "pattern: write ticket"),
    (r"^/maro\s+ticket\b", "command: /maro ticket"),
]

REVIEW_PATTERNS = [
    # Review with persona hint (security)
    (r"\breview\s+(?:this\s+)?as\s+security\b", "pattern: review as security", "security"),
    (r"\breview\s+from\s+security\b", "pattern: review from security", "security"),
    (r"\bsecurity\s+review\b", "pattern: security review", "security"),
    (r"\bsecurity\s+perspective\b", "pattern: security perspective", "security"),
    # Review with persona hint (architect)
    (r"\breview\s+(?:this\s+)?as\s+architect\b", "pattern: review as architect", "architect"),
    (r"\breview\s+from\s+architect\b", "pattern: review from architect", "architect"),
    (r"\barchitecture\s+review\b", "pattern: architecture review", "architect"),
    (r"\barchitect(?:ure)?\s+perspective\b", "pattern: architect perspective", "architect"),
    (r"\bpropose\s+(?:an?\s+)?architecture\b", "pattern: propose architecture", "architect"),
    # Review with persona hint (pm)
    (r"\breview\s+(?:this\s+)?as\s+pm\b", "pattern: review as pm", "pm"),
    (r"\breview\s+from\s+pm\b", "pattern: review from pm", "pm"),
    (r"\brequirements?\s+review\b", "pattern: requirements review", "pm"),
    (r"\bpm\s+perspective\b", "pattern: pm perspective", "pm"),
    # Generic review patterns (no persona)
    (r"^/maro\s+review\b", "command: /maro review"),
    (r"\banalyze\s+(?:this|the)\b", "pattern: analyze"),
    (r"\bevaluate\b", "pattern: evaluate"),
    (r"\bwhat\s+are\s+the\s+risks\b", "pattern: risks"),
    (r"\bidentify\s+risks\b", "pattern: identify risks"),
]

DISCUSSION_PATTERNS = [
    # Greetings
    (r"^hi$", "pattern: greeting"),
    (r"^hello$", "pattern: greeting"),
    (r"^hey$", "pattern: greeting"),
    (r"^hi!?$", "pattern: greeting"),
    (r"^hello!?$", "pattern: greeting"),
    (r"^hey!?$", "pattern: greeting"),
    # Simple questions
    (r"^what\s+can\s+you\s+do\??$", "pattern: what can you do"),
    (r"^help$", "pattern: help"),
    (r"^how\s+does\s+this\s+work\??$", "pattern: how does this work"),
]


def _check_patterns(message: str) -> Optional[IntentResult]:
    """Check message against explicit override patterns.

    Returns IntentResult if a pattern matches, None otherwise.

    Pattern priority:
    1. NEGATION patterns (e.g., "don't create ticket") -> REVIEW
    2. TICKET patterns (e.g., "create ticket") -> TICKET
    3. REVIEW patterns (e.g., "review as security") -> REVIEW
    4. DISCUSSION patterns (e.g., "hi", "help") -> DISCUSSION
    """
    message_lower = message.lower().strip()

    # Check NEGATION patterns first (highest priority)
    # These override positive TICKET patterns when user explicitly says "don't create ticket"
    for pattern_tuple in NEGATION_PATTERNS:
        pattern = pattern_tuple[0]
        reason = pattern_tuple[1]
        if re.search(pattern, message_lower, re.IGNORECASE):
            return IntentResult(
                intent=IntentType.REVIEW,
                confidence=1.0,
                reasons=[reason],
            )

    # Check TICKET patterns
    for pattern_tuple in TICKET_PATTERNS:
        pattern = pattern_tuple[0]
        reason = pattern_tuple[1]
        if re.search(pattern, message_lower, re.IGNORECASE):
            return IntentResult(
                intent=IntentType.TICKET,
                confidence=1.0,
                reasons=[reason],
            )

    # Check REVIEW patterns
    for pattern_tuple in REVIEW_PATTERNS:
        pattern = pattern_tuple[0]
        reason = pattern_tuple[1]
        persona_hint = pattern_tuple[2] if len(pattern_tuple) > 2 else None
        if re.search(pattern, message_lower, re.IGNORECASE):
            return IntentResult(
                intent=IntentType.REVIEW,
                confidence=1.0,
                persona_hint=persona_hint,
                reasons=[reason],
            )

    # Check DISCUSSION patterns
    for pattern_tuple in DISCUSSION_PATTERNS:
        pattern = pattern_tuple[0]
        reason = pattern_tuple[1]
        if re.search(pattern, message_lower, re.IGNORECASE):
            return IntentResult(
                intent=IntentType.DISCUSSION,
                confidence=1.0,
                reasons=[reason],
            )

    return None


async def _llm_classify(message: str) -> IntentResult:
    """Use LLM to classify ambiguous messages.

    Called only when pattern matching doesn't produce a result.
    """
    from src.llm import get_llm

    llm = get_llm()

    prompt = f"""Classify this user message for a Jira ticket assistant bot.

User message: "{message}"

Classify into ONE category:
- TICKET: User wants to create a Jira ticket, story, bug, or task (e.g., "we need feature X", "create story for Y", "file a bug for Z")
- REVIEW: User wants analysis, feedback, or discussion without creating a Jira ticket (e.g., "what do you think about X", "review this design", "analyze the risks")
- DISCUSSION: Casual greeting, simple question about the bot, or conversation that requires no action (e.g., "hi", "thanks", "what can you do")

Respond in this exact format:
INTENT: <TICKET|REVIEW|DISCUSSION>
CONFIDENCE: <0.0-1.0>
REASON: <brief explanation>

If the user seems to want to work on something but it's unclear if they want a ticket, lean toward TICKET.
If they're asking for feedback or analysis, choose REVIEW.
If it's just conversation, choose DISCUSSION."""

    try:
        result = await llm.chat(prompt)

        # Parse the response
        lines = result.strip().split("\n")
        intent_str = "TICKET"
        confidence = 0.7
        reason = "llm classification"

        for line in lines:
            line = line.strip()
            if line.upper().startswith("INTENT:"):
                intent_value = line.split(":", 1)[1].strip().upper()
                if intent_value in ["TICKET", "REVIEW", "DISCUSSION"]:
                    intent_str = intent_value
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    conf_value = float(line.split(":", 1)[1].strip())
                    confidence = max(0.0, min(1.0, conf_value))
                except ValueError:
                    pass
            elif line.upper().startswith("REASON:"):
                reason = f"llm: {line.split(':', 1)[1].strip()}"

        return IntentResult(
            intent=IntentType(intent_str),
            confidence=confidence,
            reasons=[reason],
        )

    except Exception as e:
        logger.warning(f"LLM intent classification failed: {e}, defaulting to TICKET")
        return IntentResult(
            intent=IntentType.TICKET,
            confidence=0.5,
            reasons=["llm classification failed, default to TICKET"],
        )


async def classify_intent(message: str) -> IntentResult:
    """Classify user message intent.

    First checks explicit override patterns (no LLM call).
    Falls back to LLM classification for ambiguous cases.

    Args:
        message: User's message text

    Returns:
        IntentResult with intent type, confidence, and reasons
    """
    # Pattern matching first (no LLM call)
    pattern_result = _check_patterns(message)
    if pattern_result is not None:
        logger.info(
            f"Intent classified by pattern: {pattern_result.intent.value}, "
            f"confidence={pattern_result.confidence}, reasons={pattern_result.reasons}"
        )
        return pattern_result

    # LLM fallback for ambiguous cases
    llm_result = await _llm_classify(message)
    logger.info(
        f"Intent classified by LLM: {llm_result.intent.value}, "
        f"confidence={llm_result.confidence}, reasons={llm_result.reasons}"
    )
    return llm_result


async def intent_router_node(state: dict) -> dict:
    """LangGraph node for intent routing.

    Gets the latest human message and classifies intent.
    Returns partial state update with intent_result.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with intent_result
    """
    from langchain_core.messages import HumanMessage

    # Get latest human message
    messages = state.get("messages", [])
    latest_human_message = None

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    if not latest_human_message:
        logger.warning("No human message found for intent classification")
        # Default to TICKET if no message
        result = IntentResult(
            intent=IntentType.TICKET,
            confidence=0.5,
            reasons=["no message found, default to TICKET"],
        )
    else:
        result = await classify_intent(latest_human_message)

    logger.info(
        f"IntentRouter: intent={result.intent.value}, "
        f"confidence={result.confidence}, reasons={result.reasons}"
    )

    return {"intent_result": result.model_dump()}
