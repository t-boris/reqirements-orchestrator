"""Question Collection Node - asks clarifying questions before proceeding.

After intent classification, this node asks LLM if it has open questions
about the topic. Questions are collected via button interactions until
LLM confirms no more questions remain.

Flow:
1. intent_router classifies intent
2. question_collection asks LLM for open questions
3. If questions exist → post with buttons, wait for answer, loop
4. When no questions → proceed to actual flow

Limits:
- Max 3 question rounds to avoid infinite loops
- Includes full context (attachments, channel history, collected answers)
"""
import logging
from typing import Any

from src.schemas.state import AgentState

logger = logging.getLogger(__name__)

# Maximum question rounds before forcing proceed
MAX_QUESTION_ROUNDS = 20


QUESTION_COLLECTION_PROMPT = '''You are checking if you need clarification before taking action.

=== USER REQUEST ===
{user_message}

=== CONTEXT ===
Intent: {intent} ({mode} mode)
{attachment_context}
{channel_context}

{collected_answers}

=== RULES ===

ONLY ask a question if it is BLOCKING - you literally cannot proceed without this information.

DO NOT ASK about:
- Implementation details (you decide those)
- Technical choices you can make yourself (cloud provider, framework, etc.)
- Things already answered in ALREADY COLLECTED section above
- Things obvious from context
- Things you can reasonably assume

GOOD questions (blocking):
- "Is this for internal team or external customers?" (changes everything)
- "Budget: enterprise or startup constraints?" (changes architecture)

BAD questions (not blocking):
- "Which cloud provider?" (you can recommend one)
- "How to handle timeouts?" (implementation detail)
- "How to deliver videos?" (you figure it out)

After 1-2 clarifying questions, you should have enough context. Don't keep asking.

=== RESPONSE ===

If you have a BLOCKING question:
QUESTION: [Your specific question]?
- Option A: [What this means - 1-2 sentences]
- Option B: [What this means - 1-2 sentences]

If you can proceed (most cases):
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
    if "NO_QUESTIONS" in response.upper():
        return None
    if response.upper().strip() == "NO":
        return None
    if response.upper().startswith("NO QUESTIONS") or response.upper().startswith("NO,"):
        return None

    # Parse QUESTION: format
    question_match = re.search(r'QUESTION:\s*(.+?\?)', response, re.IGNORECASE | re.DOTALL)
    if not question_match:
        # Try to find any question
        lines = response.split('\n')
        question_text = None
        for line in lines:
            if '?' in line and len(line.strip()) > 10:
                question_text = line.strip()
                break
        if not question_text:
            # No question found - treat as NO_QUESTIONS
            return None
    else:
        question_text = question_match.group(1).strip()

    # Parse options (lines starting with -, *, or bullet characters)
    # Include Unicode bullet characters: • ◦ ‣ ⁃
    options = []
    bullet_pattern = r'^[\-\*•◦‣⁃]\s*'
    for line in response.split('\n'):
        line = line.strip()
        # Match: bullet + label + colon + description
        opt_match = re.match(bullet_pattern + r'(.+?):\s*(.+)$', line)
        if opt_match:
            raw_label = opt_match.group(1).strip()
            # Clean up [Option A] format -> Option A
            clean_label = re.sub(r'^\[(.+?)\]$', r'\1', raw_label)[:40]
            description = opt_match.group(2).strip()
            options.append({
                "option_id": f"opt_{len(options)}",
                "label": clean_label,
                "value": clean_label.lower().replace(" ", "_")[:30],
                "description": description,
                "is_recommended": len(options) == 0,
            })
        elif re.match(bullet_pattern + r'(.+)$', line) and ':' not in line:
            # Option without description
            match = re.match(bullet_pattern + r'(.+)$', line)
            if match:
                raw_label = match.group(1).strip()
                clean_label = re.sub(r'^\[(.+?)\]$', r'\1', raw_label)[:40]
                options.append({
                    "option_id": f"opt_{len(options)}",
                    "label": clean_label,
                    "value": clean_label.lower().replace(" ", "_")[:30],
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


def _build_attachment_context(state: AgentState) -> str:
    """Build context string from attachments."""
    attachment_context = state.get("attachment_context")
    if not attachment_context:
        return ""

    parts = []

    # Get document summaries
    docs = getattr(attachment_context, 'documents', []) or []
    for doc in docs[:5]:  # Limit to 5 docs
        name = getattr(doc, 'name', 'Document')
        content = getattr(doc, 'content', '')[:500]  # First 500 chars
        if content:
            parts.append(f"[Attached: {name}]\n{content}...")

    if not parts:
        return ""

    return "=== ATTACHED DOCUMENTS ===\n" + "\n\n".join(parts)


def _build_channel_context(state: AgentState) -> str:
    """Build context string from channel history.

    Uses conversation_context (actual channel/thread messages) not internal graph messages.
    """
    parts = []

    # Use conversation_context which has actual channel messages
    conv_context = state.get("conversation_context", {})
    if conv_context:
        messages = conv_context.get("messages", [])
        for msg in messages[-10:]:  # Last 10 channel messages
            if isinstance(msg, dict):
                user = msg.get("user", "User")
                text = msg.get("text", "")
                if text and len(text) > 10:
                    parts.append(f"[{user}]: {text[:500]}")
            elif hasattr(msg, 'content'):
                content = msg.content
                if content and len(content) > 10:
                    parts.append(f"User: {content[:500]}")

    # Also check thread_context for anchor message
    thread_context = state.get("thread_context")
    if thread_context and hasattr(thread_context, 'anchor_message'):
        anchor = thread_context.anchor_message
        if anchor:
            parts.insert(0, f"[Thread anchor]: {anchor[:500]}")

    if not parts:
        return ""

    return "=== CHANNEL/THREAD CONTEXT ===\n" + "\n\n".join(parts)


async def question_collection_node(state: AgentState) -> dict[str, Any]:
    """Ask LLM if it has clarifying questions before proceeding.

    If LLM has questions → returns decision_result with action="collect_question"
    If no questions → returns with action="proceed" to continue to actual flow

    Limits to MAX_QUESTION_ROUNDS to prevent infinite loops.

    Args:
        state: Current AgentState with intent classification done

    Returns:
        Partial state update with decision_result
    """
    from src.llm import get_llm

    # Check question round limit
    question_round = state.get("question_collection_round", 0)
    if question_round >= MAX_QUESTION_ROUNDS:
        logger.info(f"Question collection: max rounds ({MAX_QUESTION_ROUNDS}) reached, proceeding")
        return {
            "decision_result": {
                "action": "proceed",
                "collected_answers": state.get("collected_answers", {}),
            },
            "question_collection_complete": True,
        }

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

    # Build context sections
    attachment_context = _build_attachment_context(state)
    channel_context = _build_channel_context(state)

    # Build collected answers context
    collected_answers = state.get("collected_answers", {})
    collected_str = ""
    if collected_answers:
        collected_str = "=== ALREADY COLLECTED ===\n"
        for q, a in collected_answers.items():
            collected_str += f"Q: {q}\nA: {a}\n\n"

    # Ask LLM for questions
    prompt = QUESTION_COLLECTION_PROMPT.format(
        user_message=user_message,
        intent=intent,
        mode=mode,
        topic=topic or user_message[:100],
        attachment_context=attachment_context,
        channel_context=channel_context,
        collected_answers=collected_str,
    )

    llm = get_llm(max_tokens=1024)
    try:
        response = await llm.chat(prompt)

        logger.info(
            f"Question collection LLM response (round {question_round + 1})",
            extra={
                "response_preview": response[:200],
                "intent": intent,
                "mode": mode,
                "collected_count": len(collected_answers),
                "round": question_round + 1,
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
            f"Question collection has question (round {question_round + 1})",
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
            "question_collection_round": question_round + 1,
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
