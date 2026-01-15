"""Review continuation node - synthesize user answers and update recommendations.

When user provides answers to open questions from a review, this node:
1. Maps answers to original questions
2. Updates architecture recommendations
3. Asks user to proceed with decision
"""
import logging
from typing import Any

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


REVIEW_CONTINUATION_PROMPT = '''You are continuing an architecture discussion.

Original review topic: {topic}

Your previous analysis:
{original_review}

User's answers to your open questions:
{user_answers}

Based on these answers, provide:
1. Brief acknowledgment of their choices (1-2 sentences)
2. How these choices affect the architecture (2-3 key implications)
3. Your updated recommendation (which option to proceed with)
4. A clear question asking if they want to proceed

Format for Slack:
- Bold: *text*
- Lists: Use bullet •
- Keep it concise (not as long as original review)
- End with a clear "Should we proceed with [approach]?" question
'''


async def review_continuation_node(state: AgentState) -> dict[str, Any]:
    """Continue review conversation after user provides answers.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with decision_result and updated review_context
    """
    from langchain_core.messages import HumanMessage
    from src.llm import get_llm

    review_context = state.get("review_context")

    if not review_context:
        logger.warning("review_continuation_node called without review_context")
        return {
            "decision_result": {
                "action": "review_continuation",
                "message": "I don't have context from a previous review. What would you like me to analyze?",
            }
        }

    # Get latest human message (user's answers)
    messages = state.get("messages", [])
    latest_human_message = ""

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    # Get review context fields
    topic = review_context.get("topic", "Architecture discussion")
    original_review = review_context.get("review_summary", "")
    persona = review_context.get("persona", "Architect")

    # Build prompt
    prompt = REVIEW_CONTINUATION_PROMPT.format(
        topic=topic,
        original_review=original_review,
        user_answers=latest_human_message,
    )

    # Call LLM
    llm = get_llm()
    try:
        continuation = await llm.chat(prompt)

        logger.info(
            "Review continuation generated",
            extra={
                "topic": topic,
                "persona": persona,
                "answers_length": len(latest_human_message),
                "continuation_length": len(continuation),
            },
        )

        # Update review_context with answers received
        # Keep context so DECISION_APPROVAL can still trigger
        updated_context = {
            **review_context,
            "answers_received": True,
            "updated_recommendation": continuation,
        }

        return {
            "decision_result": {
                "action": "review_continuation",
                "message": continuation,
                "persona": persona,
                "topic": topic,
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
