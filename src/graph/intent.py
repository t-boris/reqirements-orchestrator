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
    TICKET_ACTION = "TICKET_ACTION"  # Work with existing ticket (subtask, update, etc.)
    DECISION_APPROVAL = "DECISION_APPROVAL"  # User approving review/architecture discussion
    REVIEW_CONTINUATION = "REVIEW_CONTINUATION"  # Answering questions from previous review


class IntentResult(BaseModel):
    """Result of intent classification."""
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    persona_hint: Optional[Literal["pm", "architect", "security"]] = None
    topic: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)
    # For TICKET_ACTION intent
    ticket_key: Optional[str] = None  # Referenced ticket (e.g., "SCRUM-1111")
    action_type: Optional[str] = None  # Action: "create_subtask", "add_comment", "update", "link"


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

# TICKET_ACTION PATTERNS - checked after NEGATION but before TICKET
# These trigger work with an existing ticket reference (SCRUM-XXX format)
# Format: (pattern, reason, action_type)
TICKET_ACTION_PATTERNS = [
    # Subtask creation
    (r"create\s+subtasks?\s+(?:for\s+)?([A-Z]+-\d+)", "pattern: create subtasks for ticket", "create_subtask"),
    (r"add\s+subtasks?\s+(?:to\s+)?([A-Z]+-\d+)", "pattern: add subtasks to ticket", "create_subtask"),
    # Update ticket
    (r"update\s+([A-Z]+-\d+)", "pattern: update ticket", "update"),
    # Add comment
    (r"add\s+(?:a\s+)?comment\s+(?:to\s+)?([A-Z]+-\d+)", "pattern: add comment to ticket", "add_comment"),
    # Link to ticket
    (r"link\s+(?:this\s+)?to\s+([A-Z]+-\d+)", "pattern: link to ticket", "link"),
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

# Decision approval patterns - user approving a review/architecture discussion
# These only make sense AFTER a review has happened (check review_context in state)
DECISION_APPROVAL_PATTERNS = [
    (r"\blet'?s?\s+go\s+with\s+(?:this|that|option|approach)\b", "pattern: let's go with this"),
    (r"\bapproved\b", "pattern: approved"),
    (r"\bagreed\b", "pattern: agreed"),
    (r"\bship\s+it\b", "pattern: ship it"),
    (r"\blooks?\s+good,?\s+let'?s?\s+(?:do|proceed)\b", "pattern: looks good let's proceed"),
    (r"\bthis\s+is\s+(?:the|our)\s+approach\b", "pattern: this is the approach"),
    (r"\bI\s+(?:like|prefer)\s+(?:this|option)\b", "pattern: I like/prefer this"),
    (r"\bgo\s+(?:ahead|for\s+it)\b", "pattern: go ahead"),
    (r"\bsounds?\s+good\b", "pattern: sounds good"),
]

# Review continuation patterns - user answering questions from previous review
# These are checked ONLY when has_review_context=True
REVIEW_CONTINUATION_PATTERNS = [
    # Direct answers (key-value style)
    (r"^[\w\s]+\s*[-:]\s*\w+", "pattern: key-value answer format"),
    # Numbered answers
    (r"^\d+[.)]\s*\w+", "pattern: numbered answer"),
    # Bullet answers
    (r"^[-•]\s*\w+", "pattern: bullet answer"),
    # "For X, I'd choose Y" pattern
    (r"\bfor\s+\w+.*(?:choose|select|go with|use)\b", "pattern: for X choose Y"),
    # Multiple comma-separated items (answers to multiple questions)
    (r"^[\w\s]+,\s*[\w\s]+,\s*[\w\s]+", "pattern: comma-separated answers"),
]

# NOT continuation patterns - these override continuation detection
NOT_CONTINUATION_PATTERNS = [
    (r"\bcreate\s+(?:a\s+)?(?:new\s+)?ticket\b", "pattern: create new ticket"),
    (r"\bnew\s+(?:ticket|task|story|feature|bug)\b", "pattern: new ticket/task"),
    (r"\bpropose\s+(?:new|another|different)\b", "pattern: propose new/different"),
    (r"\blet'?s?\s+start\s+(?:over|fresh|new)\b", "pattern: start over"),
    (r"\bactually\s*,?\s*(?:I\s+)?(?:want|need)\s+(?:a\s+)?(?:new|different)\b", "pattern: actually want new/different"),
]


def _check_review_continuation(message: str) -> Optional[IntentResult]:
    """Check if message looks like answers to review questions.

    Called only when has_review_context=True.
    Returns IntentResult if continuation detected, None otherwise.
    """
    message_lower = message.lower().strip()

    # First check NOT_CONTINUATION patterns (these override)
    for pattern, reason in NOT_CONTINUATION_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            # Explicit new request - not a continuation
            return None

    # Check continuation patterns
    for pattern, reason in REVIEW_CONTINUATION_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):  # Use original case for some patterns
            return IntentResult(
                intent=IntentType.REVIEW_CONTINUATION,
                confidence=0.9,  # High but not 1.0 to allow LLM override
                reasons=[reason],
            )

    return None


def classify_intent_patterns(
    message: str,
    has_review_context: bool = False,
) -> Optional[IntentResult]:
    """Classify intent using explicit patterns only.

    Returns IntentResult if explicit pattern found, None if LLM needed.
    This function is pure/deterministic for testing.

    Pattern priority:
    1. NEGATION patterns (e.g., "don't create ticket") -> REVIEW
    2. TICKET_ACTION patterns (e.g., "create subtasks for SCRUM-1111") -> TICKET_ACTION
    3. TICKET patterns (e.g., "create ticket") -> TICKET
    4. REVIEW patterns (e.g., "review as security") -> REVIEW
    5. DECISION_APPROVAL patterns (only if has_review_context) -> DECISION_APPROVAL
    6. DISCUSSION patterns (e.g., "hi", "help") -> DISCUSSION

    Args:
        message: User's message text
        has_review_context: Whether there's a recent review to approve (Phase 14)
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

    # Check REVIEW_CONTINUATION patterns (when in review context)
    if has_review_context:
        continuation_result = _check_review_continuation(message)
        if continuation_result is not None:
            return continuation_result

    # Check TICKET_ACTION patterns (before TICKET patterns)
    # These detect explicit ticket references like "create subtasks for SCRUM-1111"
    # Need to use original message (not lowercased) to capture ticket key correctly
    for pattern_tuple in TICKET_ACTION_PATTERNS:
        pattern = pattern_tuple[0]
        reason = pattern_tuple[1]
        action_type = pattern_tuple[2]
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            # Extract ticket key from capture group (group 1)
            ticket_key = match.group(1).upper()  # Normalize to uppercase
            return IntentResult(
                intent=IntentType.TICKET_ACTION,
                confidence=1.0,
                reasons=[reason],
                ticket_key=ticket_key,
                action_type=action_type,
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

    # Check DECISION_APPROVAL patterns (only if review context exists)
    # These patterns only make sense after a review has been given
    if has_review_context:
        for pattern_tuple in DECISION_APPROVAL_PATTERNS:
            pattern = pattern_tuple[0]
            reason = pattern_tuple[1]
            if re.search(pattern, message_lower, re.IGNORECASE):
                return IntentResult(
                    intent=IntentType.DECISION_APPROVAL,
                    confidence=1.0,
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


async def _llm_classify(message: str, has_review_context: bool = False) -> IntentResult:
    """Use LLM to classify ambiguous messages.

    Called only when pattern matching doesn't produce a result.

    Args:
        message: User's message text
        has_review_context: Whether there's a recent review (biases toward REVIEW_CONTINUATION)
    """
    from src.llm import get_llm

    llm = get_llm()

    if has_review_context:
        prompt = f"""Classify this user message. IMPORTANT: This message is a reply in a thread
where the bot just provided an architecture review with open questions.

User message: "{message}"

If the message looks like answers to questions (e.g., "Option A", "Yes",
key-value pairs, bullet points, comma-separated choices), classify as REVIEW_CONTINUATION.

Only classify as TICKET if user explicitly asks for a new ticket.

Categories:
- REVIEW_CONTINUATION: Answering questions from previous review
- DECISION_APPROVAL: Approving the reviewed approach ("let's go with this", "approved")
- TICKET: Explicitly requesting a new Jira ticket
- DISCUSSION: General conversation, clarifying question

Respond in this exact format:
INTENT: <REVIEW_CONTINUATION|DECISION_APPROVAL|TICKET|DISCUSSION>
CONFIDENCE: <0.0-1.0>
REASON: <brief explanation>
"""
    else:
        prompt = f"""Classify this user message for a Jira ticket assistant bot.

User message: "{message}"

Classify into ONE category:
- TICKET: User wants to create a NEW Jira ticket, story, bug, or task (e.g., "we need feature X", "create story for Y", "file a bug for Z")
- TICKET_ACTION: User wants to work with an EXISTING ticket by reference (e.g., "create subtasks for SCRUM-123", "update PROJ-456", "add comment to ABC-789")
- REVIEW: User wants analysis, feedback, or discussion without creating a Jira ticket (e.g., "what do you think about X", "review this design", "analyze the risks")
- DISCUSSION: Casual greeting, simple question about the bot, or conversation that requires no action (e.g., "hi", "thanks", "what can you do")

Respond in this exact format:
INTENT: <TICKET|TICKET_ACTION|REVIEW|DISCUSSION>
CONFIDENCE: <0.0-1.0>
REASON: <brief explanation>
TICKET_KEY: <ticket key if TICKET_ACTION, e.g., "SCRUM-123", otherwise empty>
ACTION_TYPE: <action if TICKET_ACTION: "create_subtask", "update", "add_comment", "link", otherwise empty>

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
        ticket_key = None
        action_type = None

        for line in lines:
            line = line.strip()
            if line.upper().startswith("INTENT:"):
                intent_value = line.split(":", 1)[1].strip().upper()
                valid_intents = ["TICKET", "TICKET_ACTION", "REVIEW", "DISCUSSION", "DECISION_APPROVAL", "REVIEW_CONTINUATION"]
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
            elif line.upper().startswith("TICKET_KEY:"):
                key_value = line.split(":", 1)[1].strip().upper()
                if key_value and key_value != "EMPTY" and re.match(r"[A-Z]+-\d+", key_value):
                    ticket_key = key_value
            elif line.upper().startswith("ACTION_TYPE:"):
                action_value = line.split(":", 1)[1].strip().lower()
                if action_value in ["create_subtask", "update", "add_comment", "link"]:
                    action_type = action_value

        return IntentResult(
            intent=IntentType(intent_str),
            confidence=confidence,
            reasons=[reason],
            ticket_key=ticket_key,
            action_type=action_type,
        )

    except Exception as e:
        logger.warning(f"LLM intent classification failed: {e}, defaulting to TICKET")
        return IntentResult(
            intent=IntentType.TICKET,
            confidence=0.5,
            reasons=["llm classification failed, default to TICKET"],
        )


async def classify_intent(
    message: str,
    has_review_context: bool = False,
) -> IntentResult:
    """Classify user message intent.

    First checks explicit override patterns (no LLM call).
    Falls back to LLM classification for ambiguous cases.

    Args:
        message: User's message text
        has_review_context: Whether there's a recent review to approve (Phase 14)

    Returns:
        IntentResult with intent type, confidence, and reasons
    """
    # Pattern matching first (no LLM call)
    pattern_result = classify_intent_patterns(message, has_review_context=has_review_context)
    if pattern_result is not None:
        logger.info(
            f"Intent classified by pattern: {pattern_result.intent.value}, "
            f"confidence={pattern_result.confidence}, reasons={pattern_result.reasons}"
        )
        return pattern_result

    # LLM fallback for ambiguous cases
    llm_result = await _llm_classify(message, has_review_context=has_review_context)
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

    # Check if there's a recent review context (Phase 14 - Architecture Decisions)
    review_context = state.get("review_context")
    has_review_context = review_context is not None

    if not latest_human_message:
        logger.warning("No human message found for intent classification")
        # Default to TICKET if no message
        result = IntentResult(
            intent=IntentType.TICKET,
            confidence=0.5,
            reasons=["no message found, default to TICKET"],
        )
    else:
        result = await classify_intent(latest_human_message, has_review_context=has_review_context)

    logger.info(
        f"IntentRouter: intent={result.intent.value}, "
        f"confidence={result.confidence}, reasons={result.reasons}"
    )

    return {"intent_result": result.model_dump()}
