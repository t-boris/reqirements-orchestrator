"""ARCHITECT mode handler.

Provides substantive software architecture analysis when users discuss architecture,
propose designs, or ask for architectural opinions.

Ref: Phase 11 - Architecture Advisor
"""

import json
import logging

from pydantic import BaseModel, Field

from src.llm.client import structured_completion
from src.modes.base import ModeHandler, ModeContext, ModeResult
from src.modes.converse import FollowUpQuestion, FollowUpOption

logger = logging.getLogger(__name__)


ARCHITECT_SYSTEM = """You are an expert software architect advising a development team.

Your role is to provide real, substantive architectural analysis — not platitudes. When someone
asks an architecture question, respond with concrete patterns, tradeoffs, and recommendations.

*Analysis framework* — when evaluating architectures, always consider:
- Separation of concerns and boundary clarity
- Coupling/cohesion tradeoffs
- Data flow and ownership
- Scalability characteristics (what scales, what doesn't)
- Failure modes and resilience
- Operational complexity
- Team cognitive load

*Pattern vocabulary* — reference concrete patterns when relevant:
- Structural: Layered, Hexagonal/Ports-and-Adapters, Clean Architecture, CQRS, Event Sourcing
- Communication: Sync (REST/gRPC), Async (Events/Messages), Saga, Outbox
- Decomposition: Monolith, Modular Monolith, Microservices, Serverless
- Data: Repository, Unit of Work, Aggregate Root, Read Models/Projections
- Integration: API Gateway, BFF, Anti-Corruption Layer, Strangler Fig

*Response structure:*
- Start with a direct answer or assessment (not "great question!")
- Identify the core architectural concern
- Analyze tradeoffs with concrete pros/cons
- Recommend a specific approach with rationale
- Note assumptions and when the recommendation changes

*Thread context awareness* — use the full thread history to understand:
- What system is being discussed
- What constraints have been mentioned
- What decisions were already made
- What the team's context/scale is

*ADR recommendation:* When your analysis leads to a concrete architectural recommendation
(a specific "use X" or "go with Y" conclusion, not just exploration), set recommend_adr=True
and provide a clear ADR title (e.g., "Use Hexagonal Architecture for Payment Service").
Do NOT recommend an ADR for exploratory analysis or when the user is still exploring options.

NEVER HALLUCINATE:
- NEVER invent project details, issue keys, or data that wasn't mentioned in the thread.
- Only reference information that was explicitly provided in the conversation thread context above.

CRITICAL formatting rules (Slack mrkdwn, NOT standard markdown):
- Bold: *text* (single asterisks, NEVER **double**)
- Italic: _text_ (underscores)
- Strikethrough: ~text~
- Code: `text` or ```block```
- Bullet points: - at line start
- NEVER use **double asterisks** - Slack renders them literally
- NEVER use # headings - Slack doesn't support them
- NEVER use --- horizontal rules

When you have questions for the user:
- If there are 2-4 clear options, use question_type="choice" with options
- If it's a yes/no or confirm/deny, use question_type="confirmation" with options
- Only use question_type="open_ended" when no reasonable options can be predicted
- Keep option labels under 75 characters
- Maximum 2 follow-up questions per response"""

ARCHITECT_USER = """Thread context:
{thread_context}

Latest message from user:
"{message}"

Provide architectural analysis based on the full conversation context."""


class ArchitectResponse(BaseModel):
    """Structured response from the architecture advisor."""

    response: str = Field(description="Slack mrkdwn formatted analysis")
    patterns_referenced: list[str] = Field(
        default_factory=list,
        description="Architecture patterns referenced (e.g. 'hexagonal', 'event-sourcing')",
    )
    tradeoffs: list[str] = Field(
        default_factory=list,
        description="Key tradeoffs identified (e.g. 'Higher complexity but better isolation')",
    )
    recommend_adr: bool = Field(
        default=False,
        description="True when response contains a concrete recommendation worth recording as ADR",
    )
    adr_title: str = Field(
        default="",
        description="Pre-filled ADR title if recommend_adr is True",
    )
    follow_up_questions: list[FollowUpQuestion] = Field(
        default_factory=list,
        description="Questions to ask the user. Use 'choice' when there are 2-4 clear options. "
        "Use 'confirmation' for yes/no. Use 'open_ended' only when no reasonable options exist.",
    )


class ArchitectModeHandler(ModeHandler):
    """Handler for ARCHITECT mode.

    Provides substantive architectural analysis using a specialized system prompt
    with deep knowledge of architectural patterns, tradeoffs, and principles.

    Single LLM call (not multi-phase like JIRA). The key is the specialized
    system prompt that makes the LLM an architecture expert.
    """

    @property
    def mode_name(self) -> str:
        return "ARCHITECT"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle ARCHITECT mode message with architecture-specialized LLM response."""
        logger.info(
            f"ARCHITECT mode: user={context.user_id}, "
            f"confidence={context.intent.confidence}"
        )

        # Build thread context for LLM
        thread_context = "(No thread history)"
        if context.thread_messages:
            thread_context = "\n".join(
                f"{'Bot' if m['role'] == 'assistant' else 'User'}: {m['content']}"
                for m in context.thread_messages
            )

        # Use LLM for architecture analysis
        try:
            result = await structured_completion(
                response_model=ArchitectResponse,
                messages=[
                    {"role": "system", "content": ARCHITECT_SYSTEM},
                    {"role": "user", "content": ARCHITECT_USER.format(
                        thread_context=thread_context,
                        message=context.message,
                    )},
                ],
            )
            response = result.response
            follow_up_questions = result.follow_up_questions
            recommend_adr = result.recommend_adr
            adr_title = result.adr_title
            patterns_referenced = result.patterns_referenced
            tradeoffs = result.tradeoffs
        except Exception as e:
            logger.warning(f"LLM architecture analysis failed: {e}")
            response = (
                "I'm having trouble analyzing that architecture question right now. "
                "Could you rephrase or try again?"
            )
            follow_up_questions = []
            recommend_adr = False
            adr_title = ""
            patterns_referenced = []
            tradeoffs = []

        # Build Slack blocks with follow-up questions (same pattern as CONVERSE)
        response_blocks = None
        if follow_up_questions or recommend_adr:
            from src.slack.blocks.questions import build_question_blocks

            thread_ts = context.thread_ts or ""
            response_blocks = build_question_blocks(
                response_text=response,
                questions=follow_up_questions,
                thread_ts=thread_ts,
            )

            # If recommend_adr, append a "Record as ADR" button
            if recommend_adr and adr_title:
                adr_value = json.dumps({
                    "title": adr_title,
                    "decision_type": "architecture",
                    "decision": response[:1200],
                    "rationale": (
                        f"Patterns: {', '.join(patterns_referenced)}. "
                        f"Tradeoffs: {'; '.join(tradeoffs)}"
                    )[:500] if (patterns_referenced or tradeoffs) else "",
                    "alternatives_considered": [],
                })

                response_blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Record as ADR"},
                            "style": "primary",
                            "action_id": "confirm_record_decision",
                            "value": adr_value,
                        },
                    ],
                })

        return ModeResult(
            response_text=response,
            response_blocks=response_blocks,
            requires_confirmation=False,
        )
