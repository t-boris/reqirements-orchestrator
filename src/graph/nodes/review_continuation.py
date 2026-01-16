"""Review continuation node - synthesize user answers and update recommendations.

When user provides answers to open questions from a review, this node:
1. Maps answers to original questions
2. Updates architecture recommendations (via PATCH mode by default)
3. Asks user to proceed with decision

Patch mode outputs only changes, not full regeneration.
Full synthesis is triggered by "Show full architecture" button.
"""
import logging
from typing import Any

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


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

For FULL SYNTHESIS (user wants complete summary):
Provide a complete, detailed architecture document. Be thorough and comprehensive - cover everything discussed. Include:
1. High-level approach
2. Key components and interactions
3. Technical decisions made (with rationale)
4. Implementation considerations
5. Risks and mitigations
6. Remaining open questions (if any)

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
