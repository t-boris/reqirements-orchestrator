"""Decision extraction node for DECISION intent.

Extracts decision details from user message and creates Decision entity.
Part of Phase 30: Decision as First-Class Entity.

Phase 40: Added LLM extraction for rich context fields (rationale, context,
alternatives, consequences) from conversation history.
"""
import json
import logging
from typing import Any, Optional

from src.db.connection import get_connection
from src.db.decision_store import DecisionStore
from src.llm.client import get_llm
from src.schemas.decision import Decision, DecisionType, DecisionStatus
from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


# =============================================================================
# Rich Context Extraction (Phase 40)
# =============================================================================

RICH_CONTEXT_EXTRACTION_PROMPT = """
Extract rich context for this decision from the conversation.

Decision:
Title: {title}
Description: {description}

Conversation context:
{conversation}

Extract the following (respond with JSON):

1. rationale: 2-6 bullet points explaining WHY this decision was made
   - Each item: {{"text": "...", "weight": "primary" or "secondary"}}
   - Primary = core reasons, Secondary = supporting points
   - If not mentioned, infer from context

2. context_before: What was the status quo / situation before this decision?
   - A brief paragraph describing what existed before
   - If not mentioned, return null

3. alternatives: What other options were considered?
   - Each item: {{"option": "...", "rejected_reason": "..."}}
   - Only include if explicitly mentioned in conversation
   - If not mentioned, return empty list

4. consequences: What impact does this decision have?
   - Each item: {{"area": "...", "impact": "...", "severity": "minor" or "moderate" or "major"}}
   - Areas: Performance, Security, Complexity, Cost, Timeline, etc.
   - If not mentioned, infer obvious implications

Respond ONLY with valid JSON:
{{
  "rationale": [...],
  "context_before": "..." or null,
  "alternatives": [...],
  "consequences": [...]
}}
"""


async def extract_rich_context(
    title: str,
    description: str,
    conversation_context: str,
) -> dict:
    """Extract rich context fields from conversation using LLM.

    Uses low temperature for consistent structured output and gracefully
    handles errors to ensure decision creation is not blocked.

    Args:
        title: Decision title
        description: Decision description
        conversation_context: Recent conversation messages

    Returns:
        Dict with rationale, context_before, alternatives, consequences.
        Each field may be None/empty if not extractable.
    """
    if not conversation_context:
        # No conversation to extract from
        return {
            "rationale": None,
            "context_before": None,
            "alternatives": [],
            "consequences": [],
        }

    prompt = RICH_CONTEXT_EXTRACTION_PROMPT.format(
        title=title,
        description=description,
        conversation=conversation_context[:3000],  # Limit context size
    )

    try:
        llm = get_llm(temperature=0.3, max_tokens=1000)
        response = await llm.chat(prompt)

        # Parse JSON response - handle markdown code blocks if present
        response_text = response.strip()
        if response_text.startswith("```"):
            # Remove markdown code block wrapper
            lines = response_text.split("\n")
            # Remove first line (```json) and last line (```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            response_text = "\n".join(lines)

        result = json.loads(response_text)

        # Validate and normalize
        return {
            "rationale": result.get("rationale") or None,
            "context_before": result.get("context_before") or None,
            "alternatives": result.get("alternatives") or [],
            "consequences": result.get("consequences") or [],
        }

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse rich context JSON: {e}")
        return {
            "rationale": None,
            "context_before": None,
            "alternatives": [],
            "consequences": [],
        }
    except Exception as e:
        logger.warning(f"Failed to extract rich context: {e}")
        return {
            "rationale": None,
            "context_before": None,
            "alternatives": [],
            "consequences": [],
        }


def _build_conversation_context(messages: list, max_messages: int = 10) -> str:
    """Build conversation context string from recent messages.

    Args:
        messages: List of conversation messages
        max_messages: Maximum messages to include

    Returns:
        Formatted conversation string
    """
    recent = messages[-max_messages:] if len(messages) > max_messages else messages

    lines = []
    for msg in recent:
        content = msg.content if hasattr(msg, "content") else str(msg)
        # Truncate long messages
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(content)

    return "\n\n---\n\n".join(lines)


async def decision_extraction_node(state: AgentState) -> dict[str, Any]:
    """Extract and create decision from user message.

    When user states a decision:
    1. Extract title and description from message
    2. Determine DecisionType (from hint or default)
    3. Create Decision in PROPOSED status
    4. Return action for handler to show decision card

    Returns:
        dict with:
        - decision_result.action: "show_decision_proposal"
        - decision_result.decision_id: UUID of created decision
        - decision_result.decision: Decision object dict
    """
    messages = state.get("messages", [])
    if not messages:
        return {
            "decision_result": {
                "action": "error",
                "error": "No messages to extract decision from",
            }
        }

    # Get the latest message content
    last_message = messages[-1]
    message_content = (
        last_message.content
        if hasattr(last_message, "content")
        else str(last_message)
    )

    channel_id = state.get("channel_id", "")
    user_id = state.get("user_id", "")
    thread_ts = state.get("thread_ts")
    intent_result = state.get("intent_result", {})

    # Get type hint from intent classification
    type_hint = intent_result.get("decision_type_hint") if intent_result else None
    title_hint = intent_result.get("decision_title_hint") if intent_result else None

    # Extract decision details
    decision_type, title, description = await _extract_decision_details(
        message_content,
        type_hint=type_hint,
        title_hint=title_hint,
    )

    # Create decision in PROPOSED status
    try:
        async with get_connection() as conn:
            store = DecisionStore(conn)
            # Ensure tables exist
            await store.create_tables()

            decision = await store.create(
                channel_id=channel_id,
                decision_type=decision_type,
                title=title,
                description=description,
                created_by=user_id,
                discussion_thread_ts=thread_ts,
            )

        logger.info(
            "Decision extracted and created",
            extra={
                "decision_id": decision.id,
                "decision_type": decision_type.value,
                "title": title[:50] if len(title) > 50 else title,
                "channel_id": channel_id,
                "created_by": user_id,
            }
        )

        return {
            "decision_result": {
                "action": "show_decision_proposal",
                "decision_id": decision.id,
                "decision": {
                    "id": decision.id,
                    "channel_id": decision.channel_id,
                    "decision_type": decision.decision_type.value,
                    "title": decision.title,
                    "description": decision.description,
                    "status": decision.status.value,
                    "version": decision.version,
                    "created_by": decision.created_by,
                    "created_at": decision.created_at.isoformat(),
                },
            }
        }

    except Exception as e:
        logger.error(
            f"Failed to create decision: {e}",
            extra={
                "channel_id": channel_id,
                "user_id": user_id,
                "error": str(e),
            },
        )
        return {
            "decision_result": {
                "action": "error",
                "error": f"Failed to create decision: {str(e)}",
            }
        }


async def _extract_decision_details(
    message: str,
    *,
    type_hint: Optional[str] = None,
    title_hint: Optional[str] = None,
) -> tuple[DecisionType, str, str]:
    """Extract decision type, title, and description from message.

    Uses type_hint if provided from pattern matching, otherwise defaults to ARCH.
    Uses title_hint if available, otherwise extracts first sentence as title.

    Args:
        message: The user's message containing the decision
        type_hint: Optional decision type hint from pattern matching
        title_hint: Optional title extracted from pattern matching

    Returns:
        Tuple of (DecisionType, title, description)
    """
    # Determine decision type from hint or default
    if type_hint:
        try:
            decision_type = DecisionType(type_hint)
        except ValueError:
            # Invalid type hint, default to ARCH
            decision_type = DecisionType.ARCH
            logger.warning(f"Invalid decision type hint: {type_hint}, defaulting to ARCH")
    else:
        # Default to ARCH if no hint (most common decision type)
        decision_type = DecisionType.ARCH

    # Extract title
    if title_hint:
        title = title_hint
    else:
        # Take first sentence as title
        # Split on common sentence terminators
        first_sentence = message.split(".")[0].strip()
        # Also try splitting on newlines
        if "\n" in first_sentence:
            first_sentence = first_sentence.split("\n")[0].strip()
        # Cap at 200 chars to keep title reasonable
        title = first_sentence[:200] if len(first_sentence) > 200 else first_sentence

    # Clean up title - remove leading "We decided to" patterns if present
    title_lower = title.lower()
    prefixes_to_remove = [
        "we decided to ",
        "we decided ",
        "i decided to ",
        "i decided ",
        "the decision is to ",
        "the decision is ",
        "approved: ",
        "approved ",
        "agreed: ",
        "agreed ",
        "confirmed: ",
        "confirmed ",
        "let's go with ",
        "let's ",
        "we'll go with ",
        "we'll ",
    ]
    for prefix in prefixes_to_remove:
        if title_lower.startswith(prefix):
            title = title[len(prefix):]
            # Capitalize first letter
            if title:
                title = title[0].upper() + title[1:] if len(title) > 1 else title.upper()
            break

    # Full message becomes description
    description = message

    return decision_type, title, description
