"""Multi-ticket extraction and workflow nodes.

Handles "Create epic with N stories" requests.
Includes safety latches for quantity (>3) and size (>10k chars).
"""
import json
import logging
import re
import uuid

from src.schemas.state import (
    AgentState,
    MultiTicketState,
    MultiTicketItem,
    PendingAction,
    WorkflowStep,
    MULTI_TICKET_QUANTITY_THRESHOLD,
    MULTI_TICKET_SIZE_THRESHOLD,
)

logger = logging.getLogger(__name__)


MULTI_TICKET_EXTRACTION_PROMPT = '''Extract an epic and its stories from this request.

User request: {message}

Context (if available):
{context}

Return JSON:
{{
    "epic": {{
        "title": "Epic title",
        "description": "Epic description"
    }},
    "stories": [
        {{"title": "Story 1 title", "description": "Story 1 description"}},
        {{"title": "Story 2 title", "description": "Story 2 description"}}
    ]
}}

Be concise. Each story should be a distinct, implementable unit.
'''


async def extract_multi_ticket(state: AgentState) -> dict:
    """Extract epic + stories from user request.

    Applies safety latches:
    - >3 items: requires quantity confirmation
    - >10k chars: requires size confirmation (split into batches?)

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with multi_ticket_state and workflow routing
    """
    from langchain_core.messages import HumanMessage
    from src.llm import get_llm

    # Get user message
    messages = state.get("messages", [])
    user_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    if not user_message:
        logger.warning("No user message found for multi-ticket extraction")
        return {
            "decision_result": {
                "action": "error",
                "message": "No message found to extract tickets from",
            }
        }

    context = state.get("conversation_context", {})
    context_str = context.get("summary", "") if context else ""

    # Extract epic + stories via LLM
    llm = get_llm()
    prompt = MULTI_TICKET_EXTRACTION_PROMPT.format(
        message=user_message,
        context=context_str or "No additional context",
    )

    try:
        response = await llm.chat(prompt)
    except Exception as e:
        logger.error(f"LLM call failed in multi-ticket extraction: {e}")
        return {
            "decision_result": {
                "action": "error",
                "message": "Failed to extract tickets from request",
            }
        }

    # Parse response
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                logger.error(f"Failed to parse multi-ticket response: {response}")
                return {
                    "decision_result": {
                        "action": "error",
                        "message": "Failed to extract tickets - invalid response format",
                    }
                }
        else:
            logger.error(f"Failed to parse multi-ticket response: {response}")
            return {
                "decision_result": {
                    "action": "error",
                    "message": "Failed to extract tickets - no JSON found",
                }
            }

    # Build MultiTicketState
    items: list[MultiTicketItem] = []
    epic_id = None
    total_chars = 0

    # Add epic
    if "epic" in data and data["epic"]:
        epic_id = str(uuid.uuid4())[:8]
        epic_item: MultiTicketItem = {
            "id": epic_id,
            "type": "epic",
            "title": data["epic"].get("title", "Epic"),
            "description": data["epic"].get("description", ""),
            "parent_id": None,
        }
        items.append(epic_item)
        total_chars += len(epic_item["title"]) + len(epic_item["description"])

    # Add stories
    for story in data.get("stories", []):
        story_item: MultiTicketItem = {
            "id": str(uuid.uuid4())[:8],
            "type": "story",
            "title": story.get("title", "Story"),
            "description": story.get("description", ""),
            "parent_id": epic_id,
        }
        items.append(story_item)
        total_chars += len(story_item["title"]) + len(story_item["description"])

    if not items:
        logger.warning("No items extracted from multi-ticket request")
        return {
            "decision_result": {
                "action": "error",
                "message": "Could not extract any tickets from request",
            }
        }

    multi_state: MultiTicketState = {
        "items": items,
        "epic_id": epic_id,
        "total_chars": total_chars,
        "confirmed_quantity": False,
        "confirmed_size": False,
        "created_keys": [],
    }

    # Check safety latches
    if len(items) > MULTI_TICKET_QUANTITY_THRESHOLD and not multi_state["confirmed_quantity"]:
        logger.info(f"Quantity latch triggered: {len(items)} items > {MULTI_TICKET_QUANTITY_THRESHOLD}")
        return {
            "multi_ticket_state": multi_state,
            "pending_action": PendingAction.WAITING_QUANTITY_CONFIRM,
            "workflow_step": WorkflowStep.MULTI_TICKET_PREVIEW,
            "decision_result": {
                "action": "quantity_confirm",
                "item_count": len(items),
            },
        }

    if total_chars > MULTI_TICKET_SIZE_THRESHOLD and not multi_state["confirmed_size"]:
        logger.info(f"Size latch triggered: {total_chars} chars > {MULTI_TICKET_SIZE_THRESHOLD}")
        return {
            "multi_ticket_state": multi_state,
            "pending_action": PendingAction.WAITING_SIZE_CONFIRM,
            "workflow_step": WorkflowStep.MULTI_TICKET_PREVIEW,
            "decision_result": {
                "action": "size_confirm",
                "total_chars": total_chars,
            },
        }

    # No latches triggered - show preview
    logger.info(f"Multi-ticket preview ready: {len(items)} items, {total_chars} chars")
    return {
        "multi_ticket_state": multi_state,
        "workflow_step": WorkflowStep.MULTI_TICKET_PREVIEW,
        "pending_action": PendingAction.WAITING_APPROVAL,
        "decision_result": {
            "action": "multi_ticket_preview",
            "items": items,
        },
    }
