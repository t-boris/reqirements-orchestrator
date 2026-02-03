"""CONVERSE mode handler.

Handles casual conversation, questions, brainstorming, and clarifications.

Ref: BOT_DESIGN.md - CONVERSE Mode
"""

import logging

from src.llm.client import structured_completion
from src.modes.base import ModeHandler, ModeContext, ModeResult

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


CONVERSE_SYSTEM = """You are MARO, a Slack bot that helps software teams manage requirements, work items, and decisions.

You are having a conversation with a team member. Be helpful, concise, and professional.

Your capabilities:
- Create and track work items (stories, tasks, bugs, spikes)
- Record architectural decisions
- Facilitate team discussions and brainstorming
- Help refine requirements and acceptance criteria

Rules:
- Be concise - this is Slack, not an essay. Use short paragraphs and bullet points.
- Be substantive - provide real value, not generic platitudes.
- If the user is brainstorming, engage with the ideas and help refine them.
- If the user asks a question, answer it directly.
- If the conversation naturally leads to creating a work item, suggest it: "Want me to create a ticket for this?"
- Use Slack markdown (*bold*, _italic_, bullet points with •)
- Do NOT use headings or horizontal rules
- Keep responses under 300 words"""

CONVERSE_USER = """Message from user:
"{message}"

Respond helpfully."""


class ConverseLLMResponse(BaseModel):
    """LLM response for conversation mode."""

    response: str = Field(description="The response message to send to the user")


class ConverseModeHandler(ModeHandler):
    """Handler for CONVERSE mode.

    CONVERSE mode behavior (per BOT_DESIGN.md):
    1. Respond helpfully using LLM
    2. DO NOT create entities
    3. DO NOT emit events (except maybe MessageReceived for audit)
    4. Maintain context for future intent detection

    This is the safe fallback mode - no side effects.
    """

    @property
    def mode_name(self) -> str:
        return "CONVERSE"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle CONVERSE mode message with LLM-powered response."""
        logger.info(
            f"CONVERSE mode: user={context.user_id}, "
            f"confidence={context.intent.confidence}"
        )

        # Check if from a pregate (handled deterministically)
        if "pregate" in context.intent.reasoning.lower():
            return ModeResult(
                response_text=f"Got it. {context.intent.reasoning}",
                requires_confirmation=False,
            )

        # Use LLM for intelligent conversation
        try:
            result = await structured_completion(
                response_model=ConverseLLMResponse,
                messages=[
                    {"role": "system", "content": CONVERSE_SYSTEM},
                    {"role": "user", "content": CONVERSE_USER.format(
                        message=context.message
                    )},
                ],
            )
            response = result.response
        except Exception as e:
            logger.warning(f"LLM conversation failed: {e}")
            response = (
                "I'm having trouble processing that right now. "
                "Could you rephrase or try again?"
            )

        return ModeResult(
            response_text=response,
            requires_confirmation=False,  # CONVERSE never needs confirmation
        )
