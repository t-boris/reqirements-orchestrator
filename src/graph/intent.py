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

    JIRA_COMMAND is for natural language Jira management commands like
    "change the priority of that ticket to high" or "set status to Done".

    SYNC_REQUEST is for Jira sync commands like "update Jira issues" or
    "sync the tickets" - triggers the sync flow to compare Slack and Jira state.
    """
    TICKET = "TICKET"       # Create a NEW Jira ticket
    TICKET_ACTION = "TICKET_ACTION"  # Action on EXISTING ticket (subtasks, update, comment)
    JIRA_COMMAND = "JIRA_COMMAND"  # Edit/update/delete Jira issues via natural language
    SYNC_REQUEST = "SYNC_REQUEST"  # Sync channel decisions with Jira
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
    # For JIRA_COMMAND intent
    command_type: Optional[Literal["update", "delete"]] = None  # Type of Jira command
    command_field: Optional[str] = None  # Field to change (priority, status, assignee, etc.)
    command_value: Optional[str] = None  # New value for the field
    target_type: Optional[Literal["explicit", "contextual"]] = None  # How target was specified


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

- SYNC_REQUEST: User wants to SYNC channel decisions with Jira (bulk update)
  Key phrases: "update Jira issues", "sync Jira", "sync tickets", "update the tickets",
  "sync everything", "synchronize", "push changes to Jira", "update Jira with our decisions"
  Examples:
  - "update Jira issues" -> SYNC_REQUEST
  - "sync Jira" -> SYNC_REQUEST
  - "update the tickets" -> SYNC_REQUEST
  - "sync everything with Jira" -> SYNC_REQUEST
  - "push our decisions to Jira" -> SYNC_REQUEST
  NOTE: This is for BULK sync, not single ticket changes. Single ticket = JIRA_COMMAND

- JIRA_COMMAND: User wants to CHANGE/MODIFY an existing Jira ticket's field values
  Key verbs: change, update, set, modify, edit, delete, remove, close, mark
  Key fields: priority, status, assignee, description, summary, labels
  Target: ticket key (SCRUM-XXX) OR contextual reference ("that ticket", "the auth ticket", "it")
  Examples:
  - "change the priority of SCRUM-123 to high" -> command_type=update, field=priority, value=high
  - "update that ticket's status to Done" -> command_type=update, field=status, value=Done, target=contextual
  - "delete SCRUM-456" -> command_type=delete
  - "change the assignee to @john" -> command_type=update, field=assignee, value=@john
  - "set the status of the auth ticket to In Progress" -> command_type=update, field=status
  - "mark SCRUM-789 as done" -> command_type=update, field=status, value=done
  - "close that ticket" -> command_type=update, field=status, value=closed

- TICKET_ACTION: User wants to CREATE NEW items linked to an existing ticket
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
1. SYNC_REQUEST is for BULK sync ("update Jira issues", "sync tickets") - no specific ticket mentioned
2. JIRA_COMMAND is for MODIFYING existing ticket fields (priority, status, assignee)
3. TICKET_ACTION is for CREATING new items (stories, subtasks, comments) linked to a ticket
4. "Change priority of X" or "set status to Y" = JIRA_COMMAND
5. "Create stories for X" or "add comment to X" = TICKET_ACTION
6. If user mentions a ticket key AND wants to CREATE items under it = TICKET_ACTION
7. If user wants to MODIFY/CHANGE field values = JIRA_COMMAND
8. "Help me with X" or "I need help with X" = REVIEW (not AMBIGUOUS)
9. "Define architecture" or "design system" = REVIEW (architecture discussion)
10. Only use AMBIGUOUS if user literally could mean either "create ticket" or "discuss"
11. When in doubt between REVIEW and AMBIGUOUS, choose REVIEW
12. TICKET requires EXPLICIT new ticket creation language (no existing ticket reference)
13. "Update Jira" or "sync Jira" without a specific ticket = SYNC_REQUEST

Respond in this exact format:
INTENT: <SYNC_REQUEST|JIRA_COMMAND|TICKET_ACTION|TICKET|REVIEW|DISCUSSION|META|AMBIGUOUS>
CONFIDENCE: <0.0-1.0>
PERSONA: <pm|architect|security|none>
TICKET_KEY: <extracted ticket key like SCRUM-123, or "none" if not applicable>
ACTION_TYPE: <create_stories|create_subtask|update|add_comment|link|none>
COMMAND_TYPE: <update|delete|none>
COMMAND_FIELD: <priority|status|assignee|description|summary|labels|none>
COMMAND_VALUE: <the value to set, or "none">
TARGET_TYPE: <explicit|contextual|none>
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
        command_type = None
        command_field = None
        command_value = None
        target_type = None

        for line in lines:
            line = line.strip()
            if line.upper().startswith("INTENT:"):
                intent_value = line.split(":", 1)[1].strip().upper()
                valid_intents = ["TICKET", "TICKET_ACTION", "JIRA_COMMAND", "SYNC_REQUEST", "REVIEW", "DISCUSSION", "META", "AMBIGUOUS"]
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
            elif line.upper().startswith("COMMAND_TYPE:"):
                type_value = line.split(":", 1)[1].strip().lower()
                if type_value in ["update", "delete"]:
                    command_type = type_value
            elif line.upper().startswith("COMMAND_FIELD:"):
                field_value = line.split(":", 1)[1].strip().lower()
                if field_value and field_value != "none":
                    command_field = field_value
            elif line.upper().startswith("COMMAND_VALUE:"):
                value = line.split(":", 1)[1].strip()
                if value and value.lower() != "none":
                    command_value = value
            elif line.upper().startswith("TARGET_TYPE:"):
                type_value = line.split(":", 1)[1].strip().lower()
                if type_value in ["explicit", "contextual"]:
                    target_type = type_value
            elif line.upper().startswith("REASON:"):
                reason = f"llm: {line.split(':', 1)[1].strip()}"

        return IntentResult(
            intent=IntentType(intent_str),
            confidence=confidence,
            persona_hint=persona_hint,
            ticket_key=ticket_key,
            action_type=action_type,
            command_type=command_type,
            command_field=command_field,
            command_value=command_value,
            target_type=target_type,
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
