"""Review continuation node - synthesize user answers and update recommendations.

When user provides answers to open questions from a review, this node:
1. Maps answers to original questions
2. Updates architecture recommendations (via PATCH mode by default)
3. Asks user to proceed with decision

Patch mode outputs only changes, not full regeneration.
Full synthesis is triggered by "Show full architecture" button.

Phase 37: Unified Question Engine integration
- Uses FreeformProvider when user asks for questions
- Generates structured questions via Question Engine
"""
import logging
from typing import Any

from src.questions.freeform_provider import FreeformProvider
from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


def _wants_questions_asked(user_message: str) -> bool:
    """Detect if user wants bot to ask them questions."""
    signals = [
        "continue with questions",
        "ask me",
        "what questions",
        "your open questions",
        "ask the open questions",
        "ask your questions",
    ]
    message_lower = user_message.lower()
    return any(signal in message_lower for signal in signals)


async def _generate_review_questions(
    review_context: dict,
    num_questions: int = 3,
) -> list[str]:
    """Generate review questions using FreeformProvider.

    Args:
        review_context: Current review context
        num_questions: Number of questions to generate

    Returns:
        List of question strings
    """
    provider = FreeformProvider()

    # Build context for provider
    context = {
        "topic": review_context.get("topic", "Architecture discussion"),
        "assumptions": [],
        "constraints": [],
        "risks": [],
    }

    # Get previous summary to identify gaps
    previous_summary = (
        review_context.get("updated_recommendation") or
        review_context.get("review_summary", "")
    )

    # Determine what's missing
    missing_fields = []
    if "assumption" not in previous_summary.lower():
        missing_fields.append("assumptions")
    if "constraint" not in previous_summary.lower():
        missing_fields.append("constraints")
    if "risk" not in previous_summary.lower():
        missing_fields.append("risks")

    if not missing_fields:
        missing_fields = ["assumptions", "constraints", "risks"]

    questions = []
    for _ in range(num_questions):
        if not missing_fields:
            break
        task = await provider.generate_question(context, missing_fields)
        if task:
            questions.append(task.question_text)
            # Rotate to next field
            missing_fields = missing_fields[1:] + missing_fields[:1]

    return questions


# Patch mode prompt - outputs only changes (4 sections, max 12 bullets)
PATCH_REVIEW_PROMPT = '''Based on the user's answers, generate a PATCH update to the architecture review.

Previous review (version {version}):
{previous_summary}

User's answers:
{user_answers}

Generate a PATCH with exactly these 4 sections (max 12 bullets total):

## New Decisions
[Decisions made based on user's answers - max 3 bullets]

## New Risks
[New risks identified based on answers - max 3 bullets, or "None identified"]

## New Open Questions
[Any new questions that arose - max 3 bullets, or "None"]

## Changes Since v{version}
[What changed from previous version - max 3 bullets]

Keep it concise. This is a PATCH, not a full review.
If user wants full synthesis, they can click "Show full architecture".

Format for Slack:
- Bold: *text* (single asterisks)
- Italic: _text_ (underscores)
- Lists: Use bullet • or dash -
- NO ### headers (use *Bold Title:* instead)
'''


# Legacy full continuation prompt (still used for explicit full synthesis requests)
REVIEW_CONTINUATION_PROMPT = '''You are continuing an architecture discussion.

Original review topic: {topic}

Your previous analysis:
{original_review}

FULL CONVERSATION HISTORY:
{conversation_history}

Based on the FULL conversation above (not just the last message), provide a complete updated architecture incorporating all the information provided:

1. Acknowledge the user's answers and choices
2. Present the COMPLETE updated architecture with all sections:
   - High-level approach
   - Key components and their interactions
   - Technical decisions based on user's answers
   - Implementation considerations
   - Risks and mitigations
   - Open questions (if any remain)

Format for Slack:
- Bold: *text*
- Section headers: *Header:*
- Lists: Use bullet •
- Keep it comprehensive but focused on what's relevant given their answers
- If they asked to "show updated architecture", provide the FULL updated design, not just a summary
'''


# Single prompt that handles both intent detection and response generation
SMART_CONTINUATION_PROMPT = '''You are continuing an architecture discussion as {persona}.

Topic: {topic}

Previous architecture review:
{previous_summary}

User's latest message:
{user_message}

First, determine what the user wants:
- If they're asking for a FINAL/COMPLETE/FULL architecture summary, provide a comprehensive document
- If they're providing answers, feedback, or incremental input, provide a focused update
- If they're asking you to ASK THEM questions (e.g., "continue with your open questions", "ask me the questions"), list the open questions as a numbered list for them to answer

For FULL SYNTHESIS (user wants complete summary):
Provide a complete, detailed architecture document. Be thorough and comprehensive - cover everything discussed. Include:
1. High-level approach
2. Key components and interactions
3. Technical decisions made (with rationale)
4. Implementation considerations
5. Risks and mitigations
6. Remaining open questions (if any)

For ASK QUESTIONS (user wants YOU to ask THEM):
Key signals: "continue with questions", "ask me", "what questions", "your open questions", "ask the open questions"
When user explicitly asks you to ASK them questions:
- List 2-4 specific, numbered questions they need to answer
- Focus on the most critical open questions from the previous review
- Make questions clear and actionable
- DO NOT answer the questions yourself - just list them for the user to answer
Example response format:
"Great, here are the key questions we need to resolve:
1. [First question]?
2. [Second question]?
3. [Third question]?
Please answer any or all of these."

For INCREMENTAL UPDATE (user providing answers/feedback):
Focus on what's new or changed:
- New decisions based on user's input
- New risks identified
- New open questions (if any)
- What changed from previous version

Format for Slack:
- Bold: *text* (single asterisks)
- Lists: Use bullet • or dash -
- NO ### headers (use *Bold Title:* instead)

Do not artificially limit your response. Provide as much detail as needed for a complete answer.
'''


async def review_continuation_node(state: AgentState) -> dict[str, Any]:
    """Continue review conversation after user provides answers.

    Uses PATCH mode by default for efficiency - outputs only changes.
    Full synthesis available via "Show full architecture" button.

    Respects freeze semantics (Phase 20):
    - If review_context is None (frozen), don't continue
    - If review_context.state is POSTED or APPROVED, don't continue

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with decision_result and updated review_context
    """
    from langchain_core.messages import HumanMessage
    from src.llm import get_llm
    from src.schemas.state import ReviewState

    # Don't continue if review is frozen or already posted
    review_context = state.get("review_context")
    if not review_context:
        logger.info("No review context - cannot continue (may be frozen)")
        return {
            "decision_result": {
                "action": "error",
                "message": "No active review to continue",
            }
        }

    review_state = review_context.get("state")
    if review_state in (ReviewState.POSTED, ReviewState.APPROVED, "POSTED", "APPROVED"):
        logger.info(f"Review already {review_state} - not continuing")
        return {
            "decision_result": {
                "action": "error",
                "message": "Review already completed",
            }
        }

    review_artifact = state.get("review_artifact", {})

    # Get latest human message as user's answers
    messages = state.get("messages", [])
    user_answers = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_answers = msg.content
            break

    # Get review context fields
    topic = review_context.get("topic", "Architecture discussion")
    persona = review_context.get("persona", "Architect")

    # Calculate version number for patch tracking
    # Use review_artifact.version if exists, else review_context.version, else start at 1
    current_version = (
        review_artifact.get("version", 0) or
        review_context.get("version", 0) or
        0
    ) + 1

    # Get previous summary
    previous_summary = (
        review_context.get("updated_recommendation") or
        review_context.get("review_summary", "")
    )

    # Check if user wants to be asked questions - use FreeformProvider instead of LLM
    if _wants_questions_asked(user_answers):
        questions = await _generate_review_questions(review_context)
        if questions:
            response_content = "Great, here are the key questions we need to resolve:\n\n"
            for i, q in enumerate(questions, 1):
                response_content += f"{i}. {q}\n"
            response_content += "\nPlease answer any or all of these."

            return {
                "decision_result": {
                    "action": "review_continuation",
                    "message": response_content,
                    "persona": persona,
                    "topic": topic,
                    "version": current_version,
                    "is_questions": True,
                },
                "review_context": {
                    **review_context,
                    "version": current_version,
                    "awaiting_answers": True,
                },
            }

    # Single smart prompt - LLM decides if user wants full synthesis or patch
    prompt = SMART_CONTINUATION_PROMPT.format(
        persona=persona,
        topic=topic,
        previous_summary=previous_summary,
        user_message=user_answers,
        version=current_version - 1,
    )

    llm = get_llm(max_tokens=8192)  # Increased for longer responses
    try:
        response_content = await llm.chat(prompt)

        logger.info(
            f"Review continuation generated: {len(response_content)} chars",
            extra={
                "topic": topic,
                "persona": persona,
                "version": current_version,
                "response_length": len(response_content),
            },
        )

        # Update review_context with version tracking
        updated_context = {
            **review_context,
            "version": current_version,
            "answers_received": True,
            "updated_recommendation": response_content,
        }

        return {
            "decision_result": {
                "action": "review_continuation",
                "message": response_content,
                "persona": persona,
                "topic": topic,
                "version": current_version,
                "is_patch": True,
            },
            "review_context": updated_context,
        }

    except Exception as e:
        logger.error(f"Review continuation LLM call failed: {e}")
        return {
            "decision_result": {
                "action": "review_continuation",
                "message": f"I encountered an error processing your answers: {str(e)}",
            }
        }
