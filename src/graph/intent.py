"""Intent Router for classifying user messages.

Classifies user messages into five pure user intents:
- TICKET: User wants to create a Jira ticket
- REVIEW: User wants analysis/feedback without Jira operations
- DISCUSSION: Casual greeting, simple question, no action needed
- META: Questions about the bot itself
- AMBIGUOUS: Intent unclear - triggers scope gate for user to decide

Note: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION are now
PendingAction values handled by event_router BEFORE intent classification.
This separation ensures intent classification only handles "what user wants"
not "what system is doing".

Pattern matching is applied first for explicit overrides.
LLM classification is used only for ambiguous cases.
When in doubt, LLM returns AMBIGUOUS (not TICKET) to let user decide.
"""
import logging
import re
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """Pure user intent - what user wants (not workflow state).

    Note: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION
    are now PendingAction values in src/schemas/state.py, not intents.
    These are detected via event_router before intent classification.
    """
    TICKET = "TICKET"       # Create a Jira ticket
    REVIEW = "REVIEW"       # Analysis/feedback without Jira
    DISCUSSION = "DISCUSSION"  # Casual greeting, simple question
    META = "META"           # Questions about the bot itself
    AMBIGUOUS = "AMBIGUOUS"  # Intent unclear - triggers scope gate for user to decide


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
    # Help requests for architecture/design (always REVIEW, never TICKET)
    (r"\bhelp\s+(?:me\s+)?(?:to\s+)?(?:organize|design|architect|plan|structure)\s+(?:an?\s+)?architecture\b", "pattern: help organize/design architecture", "architect"),
    (r"\bhelp\s+(?:me\s+)?(?:with|to\s+design)\s+(?:an?\s+)?(?:architecture|system|design)\b", "pattern: help with architecture/design", "architect"),
    (r"\bhelp\s+(?:me\s+)?architect\b", "pattern: help architect", "architect"),
    (r"\bneed\s+(?:help|guidance|advice)\s+(?:with|on|for)\s+(?:architecture|design|system\s+design)\b", "pattern: need help with architecture", "architect"),
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

def classify_intent_patterns(message: str) -> Optional[IntentResult]:
    """Classify intent using explicit patterns only.

    Returns IntentResult if explicit pattern found, None if LLM needed.
    This function is pure/deterministic for testing.

    Pattern priority:
    1. NEGATION patterns (e.g., "don't create ticket") -> REVIEW
    2. TICKET patterns (e.g., "create ticket") -> TICKET
    3. REVIEW patterns (e.g., "review as security") -> REVIEW
    4. DISCUSSION patterns (e.g., "hi", "help") -> DISCUSSION

    Note: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION patterns
    are now handled via event_router/PendingAction before this is called.
    This function only handles pure user intents.

    Args:
        message: User's message text
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
    Note: has_review_context handling is no longer needed here since
    REVIEW_CONTINUATION and DECISION_APPROVAL are now PendingActions
    handled by event_router before intent classification.

    Args:
        message: User's message text
    """
    from src.llm import get_llm

    llm = get_llm()

    prompt = f"""Classify this user message for a Jira ticket assistant bot.

User message: "{message}"

Classify into ONE category:
- TICKET: User EXPLICITLY wants to create a NEW Jira ticket, story, bug, or task (e.g., "create ticket for Y", "file a bug for Z", "make a story for X")
- REVIEW: User wants analysis, feedback, or discussion without creating a Jira ticket (e.g., "review this design", "analyze the risks", "what's the best approach")
- DISCUSSION: Casual greeting, simple question about the bot, or conversation that requires no action (e.g., "hi", "thanks", "what can you do")
- META: Questions about the bot's capabilities or how it works (e.g., "what can you do?", "how do you work?")
- AMBIGUOUS: User intent is unclear - could be either a ticket request or a review request. Use when message could reasonably go either way (e.g., "what do you think about microservices?", "we should probably do something about auth", "we need to handle X")

IMPORTANT: When in doubt, choose AMBIGUOUS. Do NOT default to TICKET.
The scope gate will let the user clarify their intent.

Respond in this exact format:
INTENT: <TICKET|REVIEW|DISCUSSION|META|AMBIGUOUS>
CONFIDENCE: <0.0-1.0>
REASON: <brief explanation>

If the user's intent is unclear (could be ticket OR review), choose AMBIGUOUS.
If they're asking for feedback or analysis, choose REVIEW.
If it's just conversation, choose DISCUSSION."""

    try:
        result = await llm.chat(prompt)

        # Parse the response
        lines = result.strip().split("\n")
        intent_str = "AMBIGUOUS"  # Default to AMBIGUOUS, not TICKET
        confidence = 0.7
        reason = "llm classification"

        for line in lines:
            line = line.strip()
            if line.upper().startswith("INTENT:"):
                intent_value = line.split(":", 1)[1].strip().upper()
                valid_intents = ["TICKET", "REVIEW", "DISCUSSION", "META", "AMBIGUOUS"]
                if intent_value in valid_intents:
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
        logger.warning(f"LLM intent classification failed: {e}, defaulting to AMBIGUOUS")
        return IntentResult(
            intent=IntentType.AMBIGUOUS,
            confidence=0.5,
            reasons=["llm classification failed, default to AMBIGUOUS"],
        )


async def classify_intent(message: str) -> IntentResult:
    """Classify user message intent.

    First checks explicit override patterns (no LLM call).
    Falls back to LLM classification for ambiguous cases.

    Note: TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION
    are now handled via event_router before intent classification.
    This function only classifies pure user intents.

    Args:
        message: User's message text

    Returns:
        IntentResult with intent type, confidence, and reasons
    """
    # Pattern matching first (no LLM call)
    pattern_result = classify_intent_patterns(message)
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

    Note: This node only handles pure user intents (TICKET, REVIEW, DISCUSSION, META, AMBIGUOUS).
    TICKET_ACTION, DECISION_APPROVAL, REVIEW_CONTINUATION are now PendingActions
    handled by event_router BEFORE the graph runs.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with intent_result
    """
    from langchain_core.messages import HumanMessage

    # Check if intent is already forced (e.g., from scope_gate selection or continuation detection)
    # If so, skip classification to avoid overwriting the forced intent
    existing_intent = state.get("intent_result")
    if existing_intent:
        reasons = existing_intent.get("reasons", [])
        # Skip if any forced reason pattern is present
        forced_patterns = ["scope_gate", "event_router", "continuation"]
        if any(pattern in r for r in reasons for pattern in forced_patterns):
            logger.info(f"Skipping intent classification - already forced: {existing_intent.get('intent')}, reasons={reasons}")
            return {"intent_result": existing_intent}

    # Get latest human message
    messages = state.get("messages", [])
    latest_human_message = None

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    if not latest_human_message:
        logger.warning("No human message found for intent classification")
        # Default to AMBIGUOUS if no message (not TICKET - let user decide)
        result = IntentResult(
            intent=IntentType.AMBIGUOUS,
            confidence=0.5,
            reasons=["no message found, default to AMBIGUOUS"],
        )
    else:
        result = await classify_intent(latest_human_message)

    logger.info(
        f"IntentRouter: intent={result.intent.value}, "
        f"confidence={result.confidence}, reasons={result.reasons}"
    )

    return {"intent_result": result.model_dump()}
