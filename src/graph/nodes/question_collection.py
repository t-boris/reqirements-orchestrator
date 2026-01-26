"""Question Collection Node - asks clarifying questions before proceeding.

After intent classification, this node asks LLM if it has open questions
about the topic. Questions are collected via button interactions until
LLM confirms no more questions remain.

Flow:
1. intent_router classifies intent
2. question_collection asks LLM for open questions
3. If questions exist → post with buttons, wait for answer, loop
4. When no questions → proceed to actual flow
"""
import logging
from typing import Any

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


QUESTION_COLLECTION_PROMPT = '''You are helping gather requirements before taking action.

User's request: {user_message}
Intent: {intent} ({mode} mode)
Topic: {topic}

{collected_context}

Based on this request, do you have any clarifying questions that MUST be answered before you can proceed?

Rules:
- Only ask questions that are CRITICAL to proceeding correctly
- Maximum 1-2 questions at a time (don't overwhelm)
- Each question should have 2-4 clear answer options
- If you have enough information to proceed, say "NO_QUESTIONS"

If you have questions, respond in this EXACT format:
QUESTION: [Your question text]?
- [Option 1 label]: [Brief description]
- [Option 2 label]: [Brief description]
- [Option 3 label]: [Brief description] (optional)

If you have NO questions and are ready to proceed, respond with exactly:
NO_QUESTIONS

Examples:

Example 1 (needs clarification):
QUESTION: What type of work item should this be?
- Story: A user-facing feature or requirement
- Bug: A defect that needs fixing
- Task: Technical work or chore

Example 2 (ready to proceed):
NO_QUESTIONS
'''


def _parse_question_response(response: str) -> dict | None:
    """Parse LLM response for questions.

    Returns:
        dict with question_text and options, or None if NO_QUESTIONS
    """
    import re

    response = response.strip()

    # Check for NO_QUESTIONS
    if "NO_QUESTIONS" in response.upper() or response.upper().startswith("NO"):
        return None

    # Parse QUESTION: format
    question_match = re.search(r'QUESTION:\s*(.+?\?)', response, re.IGNORECASE | re.DOTALL)
    if not question_match:
        # Try to find any question
        lines = response.split('\n')
        for line in lines:
            if '?' in line and len(line.strip()) > 10:
                question_text = line.strip()
                break
        else:
            return None
    else:
        question_text = question_match.group(1).strip()

    # Parse options (lines starting with -)
    options = []
    for line in response.split('\n'):
        line = line.strip()
        opt_match = re.match(r'^[\-\*]\s*(.+?):\s*(.+)$', line)
        if opt_match:
            label = opt_match.group(1).strip()[:40]
            description = opt_match.group(2).strip()
            options.append({
                "option_id": f"opt_{len(options)}",
                "label": label,
                "value": label.lower().replace(" ", "_")[:30],
                "description": description,
                "is_recommended": len(options) == 0,
            })
        elif re.match(r'^[\-\*]\s*(.+)$', line) and ':' not in line:
            # Option without description
            label = re.match(r'^[\-\*]\s*(.+)$', line).group(1).strip()[:40]
            options.append({
                "option_id": f"opt_{len(options)}",
                "label": label,
                "value": label.lower().replace(" ", "_")[:30],
                "description": "",
                "is_recommended": len(options) == 0,
            })

    if not options:
        # No structured options, let user reply freely
        return {
            "question_text": question_text,
            "options": None,
        }

    return {
        "question_text": question_text,
        "options": options,
    }


async def question_collection_node(state: AgentState) -> dict[str, Any]:
    """Ask LLM if it has clarifying questions before proceeding.

    If LLM has questions → returns decision_result with action="collect_question"
    If no questions → returns with action="proceed" to continue to actual flow

    Args:
        state: Current AgentState with intent classification done

    Returns:
        Partial state update with decision_result
    """
    from src.llm import get_llm

    # Get classified intent info
    envelope = state.get("envelope")
    intent_result = state.get("intent_result", {})

    mode = "unknown"
    intent = "unknown"
    topic = intent_result.get("topic", "")

    if envelope:
        mode = envelope.mode.value if hasattr(envelope.mode, 'value') else str(envelope.mode)
        intent = envelope.intent.value if hasattr(envelope.intent, 'value') else str(envelope.intent)

    # Get user message
    user_message = state.get("user_message", "")
    if not user_message:
        messages = state.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "content"):
                user_message = msg.content
                break

    # Build collected context from previous answers
    collected_answers = state.get("collected_answers", {})
    collected_context = ""
    if collected_answers:
        collected_context = "Already collected information:\n"
        for q, a in collected_answers.items():
            collected_context += f"- {q}: {a}\n"

    # Ask LLM for questions
    prompt = QUESTION_COLLECTION_PROMPT.format(
        user_message=user_message,
        intent=intent,
        mode=mode,
        topic=topic or user_message[:100],
        collected_context=collected_context,
    )

    llm = get_llm(max_tokens=1024)
    try:
        response = await llm.chat(prompt)

        logger.info(
            f"Question collection LLM response",
            extra={
                "response_preview": response[:200],
                "intent": intent,
                "mode": mode,
                "collected_count": len(collected_answers),
            }
        )

        # Parse response
        question_data = _parse_question_response(response)

        if question_data is None:
            # No questions - proceed to actual flow
            logger.info("Question collection complete - no more questions, proceeding to flow")
            return {
                "decision_result": {
                    "action": "proceed",
                    "collected_answers": collected_answers,
                },
                "question_collection_complete": True,
            }

        # Has questions - return for posting
        logger.info(
            f"Question collection has question",
            extra={
                "question": question_data["question_text"][:50],
                "options_count": len(question_data.get("options") or []),
            }
        )

        return {
            "decision_result": {
                "action": "collect_question",
                "question": question_data,
                "intent": intent,
                "mode": mode,
            },
            "question_collection_complete": False,
        }

    except Exception as e:
        logger.error(f"Question collection LLM call failed: {e}")
        # On error, proceed without questions
        return {
            "decision_result": {
                "action": "proceed",
                "collected_answers": collected_answers,
            },
            "question_collection_complete": True,
        }
