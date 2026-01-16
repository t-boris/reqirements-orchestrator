"""Intent Router for classifying user messages.

Classifies user messages into five pure user intents:
- TICKET: User wants to create a Jira ticket
- REVIEW: User wants analysis/feedback without Jira operations
- DISCUSSION: Casual greeting, simple question, no action needed
- META: Questions about the bot itself
- AMBIGUOUS: Intent unclear - triggers scope gate for user to decide

ALL classification is done by LLM with full conversation context.
No pattern matching - LLM makes all decisions based on complete context.
"""
import logging
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """Pure user intent - what user wants (not workflow state).

    Note: DECISION_APPROVAL, REVIEW_CONTINUATION are now PendingAction values
    in src/schemas/state.py, detected via event_router before intent classification.

    TICKET_ACTION is still classified here because it requires LLM to extract
    the ticket_key from the user's message.
    """
    TICKET = "TICKET"       # Create a NEW Jira ticket
    TICKET_ACTION = "TICKET_ACTION"  # Action on EXISTING ticket (subtasks, update, comment)
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
    # For TICKET_ACTION intent
    ticket_key: Optional[str] = None  # e.g., "SCRUM-113"
    action_type: Optional[Literal["create_subtask", "create_stories", "update", "add_comment", "link"]] = None


async def _llm_classify(message: str, conversation_context: dict | None = None) -> IntentResult:
    """Use LLM to classify user intent with full conversation context.

    Args:
        message: User's current message text
        conversation_context: Full conversation history (messages + summary)
    """
    from src.llm import get_llm

    llm = get_llm()

    # Build context string from conversation history
    context_str = ""
    if conversation_context:
        messages = conversation_context.get("messages", [])
        summary = conversation_context.get("summary")

        if summary:
            context_str += f"Conversation summary:\n{summary}\n\n"

        if messages:
            context_str += "Recent messages:\n"
            for msg in messages[-15:]:  # Last 15 messages for context
                user = msg.get("user", "unknown")
                text = msg.get("text", "")
                if text:
                    context_str += f"[{user}]: {text}\n"
            context_str += "\n"

    prompt = f"""You are classifying user intent for a Slack bot that helps with Jira tickets and architecture discussions.

{f"CONVERSATION CONTEXT:{chr(10)}{context_str}" if context_str else ""}
CURRENT USER MESSAGE: "{message}"

Classify the user's intent into ONE category:

- TICKET_ACTION: User wants to perform an action on an EXISTING Jira ticket
  The message must reference a specific ticket key (e.g., SCRUM-123, PROJ-456).
  Examples:
  - "create user stories for SCRUM-113" -> action_type=create_stories
  - "create subtasks for PROJ-456" -> action_type=create_subtask
  - "add a comment to SCRUM-123" -> action_type=add_comment
  - "update PROJ-789 with the new requirements" -> action_type=update
  - "break down SCRUM-100 into stories" -> action_type=create_stories

- TICKET: User wants to create a NEW Jira ticket (no existing ticket referenced)
  Examples: "create a ticket for X", "file a bug", "make a Jira story"

- REVIEW: User wants help, analysis, discussion, or feedback WITHOUT creating a ticket
  Examples: "help me define architecture", "review this design", "what's the best approach",
  "I need help with X", "analyze the risks", "let's discuss Y"
  This is the DEFAULT for most help/discussion requests!

- DISCUSSION: Pure greeting or meta-question with no actionable request
  Examples: "hi", "hello", "thanks"

- META: Questions about the bot itself
  Examples: "what can you do?", "how do you work?"

- AMBIGUOUS: ONLY use when the message is truly unclear AND could equally be ticket OR review
  This should be RARE. Most requests are clearly REVIEW (discussion/help) or TICKET (explicit creation).

IMPORTANT RULES:
1. If user mentions a ticket key (like SCRUM-XXX, PROJ-XXX) AND wants to create items under it = TICKET_ACTION
2. "Create stories/subtasks for [TICKET]" = TICKET_ACTION with action_type=create_stories or create_subtask
3. "Help me with X" or "I need help with X" = REVIEW (not AMBIGUOUS)
4. "Define architecture" or "design system" = REVIEW (architecture discussion)
5. Only use AMBIGUOUS if user literally could mean either "create ticket" or "discuss"
6. When in doubt between REVIEW and AMBIGUOUS, choose REVIEW
7. TICKET requires EXPLICIT new ticket creation language (no existing ticket reference)

Respond in this exact format:
INTENT: <TICKET_ACTION|TICKET|REVIEW|DISCUSSION|META|AMBIGUOUS>
CONFIDENCE: <0.0-1.0>
PERSONA: <pm|architect|security|none>
TICKET_KEY: <extracted ticket key like SCRUM-123, or "none" if not applicable>
ACTION_TYPE: <create_stories|create_subtask|update|add_comment|link|none>
REASON: <brief explanation>"""

    try:
        result = await llm.chat(prompt)

        # Parse the response
        lines = result.strip().split("\n")
        intent_str = "REVIEW"  # Default to REVIEW, not AMBIGUOUS
        confidence = 0.8
        reason = "llm classification"
        persona_hint = None
        ticket_key = None
        action_type = None

        for line in lines:
            line = line.strip()
            if line.upper().startswith("INTENT:"):
                intent_value = line.split(":", 1)[1].strip().upper()
                valid_intents = ["TICKET", "TICKET_ACTION", "REVIEW", "DISCUSSION", "META", "AMBIGUOUS"]
                if intent_value in valid_intents:
                    intent_str = intent_value
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    conf_value = float(line.split(":", 1)[1].strip())
                    confidence = max(0.0, min(1.0, conf_value))
                except ValueError:
                    pass
            elif line.upper().startswith("PERSONA:"):
                persona_value = line.split(":", 1)[1].strip().lower()
                if persona_value in ["pm", "architect", "security"]:
                    persona_hint = persona_value
            elif line.upper().startswith("TICKET_KEY:"):
                key_value = line.split(":", 1)[1].strip().upper()
                if key_value and key_value != "NONE":
                    ticket_key = key_value
            elif line.upper().startswith("ACTION_TYPE:"):
                type_value = line.split(":", 1)[1].strip().lower()
                valid_actions = ["create_stories", "create_subtask", "update", "add_comment", "link"]
                if type_value in valid_actions:
                    action_type = type_value
            elif line.upper().startswith("REASON:"):
                reason = f"llm: {line.split(':', 1)[1].strip()}"

        return IntentResult(
            intent=IntentType(intent_str),
            confidence=confidence,
            persona_hint=persona_hint,
            ticket_key=ticket_key,
            action_type=action_type,
            reasons=[reason],
        )

    except Exception as e:
        logger.warning(f"LLM intent classification failed: {e}, defaulting to REVIEW")
        return IntentResult(
            intent=IntentType.REVIEW,
            confidence=0.5,
            reasons=["llm classification failed, default to REVIEW"],
        )


async def classify_intent(message: str, conversation_context: dict | None = None) -> IntentResult:
    """Classify user message intent using LLM with full context.

    Args:
        message: User's message text
        conversation_context: Full conversation history for context

    Returns:
        IntentResult with intent type, confidence, and reasons
    """
    result = await _llm_classify(message, conversation_context)
    logger.info(
        f"Intent classified by LLM: {result.intent.value}, "
        f"confidence={result.confidence}, persona={result.persona_hint}, reasons={result.reasons}"
    )
    return result


async def intent_router_node(state: dict) -> dict:
    """LangGraph node for intent routing.

    Gets the latest human message and classifies intent using LLM with full context.
    Returns partial state update with intent_result.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with intent_result
    """
    from langchain_core.messages import HumanMessage

    # Check if intent is already forced (e.g., from scope_gate selection or continuation detection)
    existing_intent = state.get("intent_result")
    if existing_intent:
        reasons = existing_intent.get("reasons", [])
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
        result = IntentResult(
            intent=IntentType.REVIEW,
            confidence=0.5,
            reasons=["no message found, default to REVIEW"],
        )
    else:
        # Get conversation context for LLM
        conversation_context = state.get("conversation_context")
        result = await classify_intent(latest_human_message, conversation_context)

    logger.info(
        f"IntentRouter: intent={result.intent.value}, "
        f"confidence={result.confidence}, reasons={result.reasons}"
    )

    return {"intent_result": result.model_dump()}
