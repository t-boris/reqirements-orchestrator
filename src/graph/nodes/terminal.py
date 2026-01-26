"""Terminal response node (Phase 39).

Handles terminal intents that require single response then END:
- DISCUSSION (casual chat)
- META (about the bot)

These don't loop or require follow-up.
"""
import logging
from typing import Any, TYPE_CHECKING

from src.schemas.intent import Intent

if TYPE_CHECKING:
    from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


async def terminal_response_node(state: "AgentState") -> dict[str, Any]:
    """Generate terminal response for CHAT/META intents.

    Single response, then graph should END.

    Args:
        state: AgentState with envelope and event

    Returns:
        {"response": str, "terminal": True}
    """
    from src.llm import get_llm

    envelope = state.get("envelope")
    event = state.get("event", {})
    message = event.get("text", "")

    intent = envelope.intent if envelope else Intent.DISCUSSION

    if intent == Intent.META:
        response = await _generate_meta_response(message)
    else:
        response = await _generate_chat_response(message)

    logger.info(f"Terminal response for {intent.value}: {len(response)} chars")

    return {
        "response": response,
        "terminal": True,
    }


async def _generate_meta_response(message: str) -> str:
    """Generate response about the bot itself."""
    from src.llm import get_llm

    llm = get_llm()

    prompt = f"""The user is asking about you (the Requirements Orchestrator bot).

MESSAGE: "{message}"

Respond briefly about your capabilities:
- You help teams manage requirements, work items, and decisions
- You can create and refine drafts
- You can sync work to Jira
- You support architectural reviews
- You track decisions and their rationale

Keep response friendly and concise (2-3 sentences)."""

    return await llm.chat(prompt)


async def _generate_chat_response(message: str) -> str:
    """Generate casual chat response."""
    from src.llm import get_llm

    llm = get_llm()

    prompt = f"""The user is having a casual conversation.

MESSAGE: "{message}"

Respond naturally and briefly. If they're greeting you, greet back.
If they're asking a general question, answer concisely.

Keep response friendly and short (1-2 sentences)."""

    return await llm.chat(prompt)


def is_terminal_response(state: dict) -> bool:
    """Check if last response was terminal (should END graph)."""
    return state.get("terminal", False)
