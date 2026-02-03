"""CONVERSE mode handler.

Handles casual conversation, questions, brainstorming, and clarifications.

Ref: BOT_DESIGN.md - CONVERSE Mode
"""

import logging
from typing import Literal

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
- Keep responses under 300 words

CRITICAL formatting rules (Slack mrkdwn, NOT standard markdown):
- Bold: *text* (single asterisks, NEVER **double**)
- Italic: _text_ (underscores)
- Strikethrough: ~text~
- Code: `text` or ```block```
- Bullet points: • or - at line start
- NEVER use **double asterisks** - Slack renders them literally
- NEVER use # headings - Slack doesn't support them
- NEVER use --- horizontal rules

When you have questions for the user:
- If there are 2-4 clear options, use question_type="choice" with options
- If it's a yes/no or confirm/deny, use question_type="confirmation" with options [{"label": "Yes", "description": "..."}, {"label": "No", "description": "..."}]
- Only use question_type="open_ended" when no reasonable options can be predicted
- Keep option labels under 75 characters
- Always include the most likely option first
- Maximum 2 follow-up questions per response"""

CONVERSE_USER = """Thread context:
{thread_context}

Latest message from user:
"{message}"

Respond helpfully based on the full conversation context."""


class FollowUpOption(BaseModel):
    """An option for a follow-up question button."""

    label: str = Field(description="Short button label, max 75 chars")
    description: str = Field(description="What this option means")


class FollowUpQuestion(BaseModel):
    """A structured follow-up question for the user."""

    question_text: str = Field(description="The question to ask the user")
    question_type: Literal["choice", "confirmation", "open_ended"] = Field(
        description="choice = buttons, confirmation = yes/no, open_ended = free text"
    )
    options: list[FollowUpOption] = Field(
        default_factory=list,
        description="Options for choice/confirmation types. Empty for open_ended.",
    )
    priority: int = Field(
        default=0,
        description="Higher priority questions should be asked first",
    )


class ConverseLLMResponse(BaseModel):
    """LLM response for conversation mode."""

    response: str = Field(description="The response message to send to the user")
    follow_up_questions: list[FollowUpQuestion] = Field(
        default_factory=list,
        description="Questions to ask the user. Use 'choice' when there are 2-4 clear options. "
        "Use 'confirmation' for yes/no. Use 'open_ended' only when no reasonable options exist.",
    )


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

        # Build thread context for LLM
        thread_context = "(No thread history)"
        if context.thread_messages:
            thread_context = "\n".join(
                f"{'Bot' if m['role'] == 'assistant' else 'User'}: {m['content']}"
                for m in context.thread_messages
            )

        # Use LLM for intelligent conversation
        try:
            result = await structured_completion(
                response_model=ConverseLLMResponse,
                messages=[
                    {"role": "system", "content": CONVERSE_SYSTEM},
                    {"role": "user", "content": CONVERSE_USER.format(
                        thread_context=thread_context,
                        message=context.message,
                    )},
                ],
            )
            response = result.response
            follow_up_questions = result.follow_up_questions
        except Exception as e:
            logger.warning(f"LLM conversation failed: {e}")
            response = (
                "I'm having trouble processing that right now. "
                "Could you rephrase or try again?"
            )
            follow_up_questions = []

        # Build Slack blocks with buttons if there are follow-up questions
        response_blocks = None
        if follow_up_questions:
            from src.slack.blocks.questions import build_question_blocks

            thread_ts = context.thread_ts or ""
            response_blocks = build_question_blocks(
                response_text=response,
                questions=follow_up_questions,
                thread_ts=thread_ts,
            )

        return ModeResult(
            response_text=response,
            response_blocks=response_blocks,
            requires_confirmation=False,  # CONVERSE never needs confirmation
        )
