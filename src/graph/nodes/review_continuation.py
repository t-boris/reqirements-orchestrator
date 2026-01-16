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


async def review_continuation_node(state: AgentState) -> dict[str, Any]:
    """Continue review conversation after user provides answers.

    Uses PATCH mode by default for efficiency - outputs only changes.
    Full synthesis available via "Show full architecture" button.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with decision_result and updated review_context
    """
    from langchain_core.messages import HumanMessage
    from src.llm import get_llm

    review_context = state.get("review_context")
    review_artifact = state.get("review_artifact", {})

    if not review_context:
        logger.warning("review_continuation_node called without review_context")
        return {
            "decision_result": {
                "action": "review_continuation",
                "message": "I don't have context from a previous review. What would you like me to analyze?",
            }
        }

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

    # Get previous summary for patch generation
    previous_summary = (
        review_context.get("updated_recommendation") or
        review_context.get("review_summary", "")
    )

    # Use PATCH mode by default (efficient, 4 sections, max 12 bullets)
    prompt = PATCH_REVIEW_PROMPT.format(
        version=current_version - 1,
        previous_summary=previous_summary,
        user_answers=user_answers,
    )

    # Call LLM
    llm = get_llm()
    try:
        patch_content = await llm.chat(prompt)

        logger.info(
            "Review continuation generated (patch mode)",
            extra={
                "topic": topic,
                "persona": persona,
                "version": current_version,
                "patch_length": len(patch_content),
            },
        )

        # Update review_context with version tracking
        updated_context = {
            **review_context,
            "version": current_version,
            "answers_received": True,
            "updated_recommendation": patch_content,
        }

        return {
            "decision_result": {
                "action": "review_continuation",
                "message": patch_content,
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
