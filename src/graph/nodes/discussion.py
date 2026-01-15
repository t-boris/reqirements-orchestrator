"""Discussion node - single response for casual interactions.

Handles DISCUSSION intent: greetings, simple questions, casual conversation.
Generates a brief, helpful response WITHOUT:
- Creating threads
- Creating drafts
- Calling Jira
- Running validators

This node ONLY generates a response and stops.
"""
import logging

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


DISCUSSION_PROMPT = '''You are MARO, a helpful assistant that turns discussions into Jira tickets and provides architectural/security reviews.

User said: {message}

Respond in 1-2 sentences max. Be helpful but brief.
If they're asking what you can do, mention: creating Jira tickets, reviewing ideas as PM/Architect/Security.
Don't offer to do anything specific unless asked.
End with a natural conversation prompt if appropriate.'''


async def discussion_node(state: AgentState) -> dict:
    """LangGraph node for discussion flow.

    Generates a brief, helpful response for casual interactions.
    Does NOT create draft, call Jira, or run validators.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with decision_result containing discussion response
    """
    from langchain_core.messages import HumanMessage
    from src.llm import get_llm

    # Get latest human message
    messages = state.get("messages", [])
    latest_human_message = None

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    if not latest_human_message:
        logger.warning("No human message found for discussion node")
        response_text = "Hi! I help turn discussions into Jira tickets and review ideas. What would you like to work on?"
    else:
        try:
            llm = get_llm()
            prompt = DISCUSSION_PROMPT.format(message=latest_human_message)
            response_text = await llm.chat(prompt)
        except Exception as e:
            logger.warning(f"LLM call failed in discussion node: {e}")
            response_text = "Hi! I help turn discussions into Jira tickets and review ideas as PM, Architect, or Security. What would you like to work on?"

    logger.info("Discussion response generated")

    return {
        "decision_result": {
            "action": "discussion",
            "message": response_text,
        }
    }
