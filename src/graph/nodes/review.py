"""Review node - persona-based architectural analysis without Jira operations.

When user asks for review/analysis, this node provides thoughtful architectural
feedback like a senior engineer, without triggering the ticket creation pipeline.

The review is conversational and thorough - a discussion, not a ticket.
"""
import logging
from typing import Any

from src.schemas.state import AgentState
from src.personas import get_persona, get_default_persona, PersonaName

logger = logging.getLogger(__name__)


REVIEW_PROMPT = '''You are {persona_name}, a senior {persona_role}.

{persona_overlay}

Analyze this request thoughtfully, as if thinking out loud:

{context}

User request: {message}

Provide analysis covering:
1. *Understanding* - What you understand about the request
2. *Components & Flows* - Key technical elements involved
3. *Risks & Concerns* - What could go wrong
4. *Alternatives* - Other approaches to consider
5. *Open Questions* - What needs clarification

Be conversational and thorough. This is a discussion, not a ticket.
Think out loud like a senior engineer would.

IMPORTANT: Format for Slack (not Markdown):
- Bold: *text* (single asterisks)
- Italic: _text_ (underscores)
- Code: `code`
- Lists: Use bullet character • or dash -
- NO ### headers (use *Bold Title* instead)
- NO **double asterisks**
'''


def _get_persona_for_review(state: AgentState) -> tuple[str, str, str]:
    """Determine which persona to use for the review.

    Returns:
        Tuple of (persona_name, persona_role, prompt_overlay)

    Persona selection logic:
    1. If intent_result.persona_hint exists -> use that persona
    2. Elif state.persona exists -> use current persona
    3. Else -> default to "architect" (most common for reviews)
    """
    intent_result = state.get("intent_result", {})
    persona_hint = intent_result.get("persona_hint")
    current_persona = state.get("persona")

    # Determine which persona to use
    if persona_hint:
        # Intent classification suggested a specific persona
        persona_name_str = persona_hint
    elif current_persona:
        # Use current persona from state
        persona_name_str = current_persona
    else:
        # Default to architect for reviews
        persona_name_str = "architect"

    # Map string to PersonaName enum
    persona_map = {
        "pm": PersonaName.PM,
        "architect": PersonaName.ARCHITECT,
        "security": PersonaName.SECURITY,
    }
    persona_enum = persona_map.get(persona_name_str, PersonaName.ARCHITECT)

    # Get persona config
    persona_config = get_persona(persona_enum)

    return (
        persona_config.display_name,
        _get_role_for_persona(persona_enum),
        persona_config.prompt_overlay,
    )


def _get_role_for_persona(persona: PersonaName) -> str:
    """Get role description for persona."""
    roles = {
        PersonaName.PM: "Product Manager",
        PersonaName.ARCHITECT: "Technical Architect",
        PersonaName.SECURITY: "Security Analyst",
    }
    return roles.get(persona, "Technical Architect")


def _build_context_string(state: AgentState) -> str:
    """Build context string from conversation context and channel context."""
    parts = []

    # Conversation context (Phase 11)
    conversation_context = state.get("conversation_context")
    if conversation_context:
        summary = conversation_context.get("summary")
        if summary:
            parts.append(f"Conversation background:\n{summary}")

        # Include recent messages if available
        messages = conversation_context.get("messages", [])
        if messages:
            recent = messages[-5:]  # Last 5 messages for context
            msg_texts = []
            for msg in recent:
                user = msg.get("user", "unknown")
                text = msg.get("text", "")[:200]  # Truncate long messages
                msg_texts.append(f"- {user}: {text}")
            if msg_texts:
                parts.append(f"Recent conversation:\n" + "\n".join(msg_texts))

    # Channel context (Phase 8)
    channel_context = state.get("channel_context")
    if channel_context:
        system_context = channel_context.get("system_context")
        if system_context:
            parts.append(f"Project context:\n{system_context}")

    if parts:
        return "\n\n".join(parts)
    return "No additional context available."


async def review_node(state: AgentState) -> dict[str, Any]:
    """Generate persona-based analysis for review requests.

    This node is used for REVIEW intent - when user wants analysis/feedback
    without creating a Jira ticket. It produces thoughtful, conversational
    analysis like a senior engineer would.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with decision_result containing:
        - action: "review"
        - message: analysis text
        - persona: persona name used
        - topic: topic from intent result (if any)
    """
    from langchain_core.messages import HumanMessage
    from src.llm import get_llm

    # Get intent result for persona hint and topic
    intent_result = state.get("intent_result", {})
    topic = intent_result.get("topic")

    # Determine persona
    persona_name, persona_role, persona_overlay = _get_persona_for_review(state)

    # Get latest human message
    messages = state.get("messages", [])
    latest_human_message = ""

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    if not latest_human_message:
        logger.warning("No human message found for review")
        return {
            "decision_result": {
                "action": "review",
                "message": "I don't see a message to review. What would you like me to analyze?",
                "persona": persona_name,
                "topic": topic,
            }
        }

    # Build context string
    context = _build_context_string(state)

    # Build prompt
    prompt = REVIEW_PROMPT.format(
        persona_name=persona_name,
        persona_role=persona_role,
        persona_overlay=persona_overlay,
        context=context,
        message=latest_human_message,
    )

    # Call LLM
    llm = get_llm()
    try:
        analysis = await llm.chat(prompt)

        logger.info(
            "Review node generated analysis",
            extra={
                "persona": persona_name,
                "topic": topic,
                "message_length": len(latest_human_message),
                "analysis_length": len(analysis),
            },
        )

        return {
            "decision_result": {
                "action": "review",
                "message": analysis,
                "persona": persona_name,
                "topic": topic,
            }
        }

    except Exception as e:
        logger.error(f"Review node LLM call failed: {e}")
        return {
            "decision_result": {
                "action": "review",
                "message": f"I encountered an error while generating the analysis: {str(e)}",
                "persona": persona_name,
                "topic": topic,
            }
        }
