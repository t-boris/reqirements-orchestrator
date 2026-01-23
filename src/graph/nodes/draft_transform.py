"""Draft Transform node - handles structural mutations of StructuredDraft.

Routes from DRAFT_TRANSFORM intent. Mutates draft structure based on
transform_operation and returns to decision flow for validation.

Phase 28 requirement R2: User decisions must mutate Draft form.
Phase 28 requirement R11: Transition from decision to action is mandatory.
"""
import json
import logging
from typing import Any

from src.llm import get_llm
from src.schemas.state import AgentState
from src.schemas.structured_draft import (
    DraftScope,
    StructuredDraft,
)

logger = logging.getLogger(__name__)


TRANSFORM_PARAMS_PROMPT = '''Extract parameters for a draft transformation.

User message: {message}
Transform operation: {operation}
Current draft:
- Kind: {draft_kind}
- Items: {item_summary}

Based on the operation type, extract the relevant parameters.

Operations and their parameters:
- split_to_plan: item_titles (list of strings for new items)
- add_items: items (list of {{title, issue_type, goal}})
- merge_items: item_ids (list), merged_title (string, optional)
- elevate_to_epic: item_id (string, optional - uses first item if not specified)
- decompose_to_stories: epic_id (string, optional), story_titles (list)
- change_scope: scope (single, epics_only, or full_plan)
- remove_items: item_ids (list)

Return JSON with only the relevant parameters for this operation.
Example for split_to_plan: {{"item_titles": ["Epic 1", "Epic 2"]}}
Example for change_scope: {{"scope": "epics_only"}}
Example for add_items: {{"items": [{{"title": "Story 1", "issue_type": "story"}}]}}

If you cannot extract specific parameters, return {{}}.

JSON response:'''


async def _extract_transform_params(
    message: str,
    operation: str,
    draft: StructuredDraft,
) -> dict[str, Any]:
    """Extract transform parameters from user message using LLM.

    Args:
        message: The user's message
        operation: The transform operation being performed
        draft: Current draft for context

    Returns:
        Dict of parameters for the transform operation
    """
    # Build item summary for context
    item_summary = "None"
    if draft.items:
        item_lines = []
        for i, item in enumerate(draft.items):
            item_lines.append(
                f"  {i+1}. [{item.id[:8]}] {item.issue_type.value}: "
                f"{item.title or '(untitled)'}"
            )
        item_summary = "\n" + "\n".join(item_lines)

    prompt = TRANSFORM_PARAMS_PROMPT.format(
        message=message,
        operation=operation,
        draft_kind=draft.kind.value,
        item_summary=item_summary,
    )

    try:
        llm = get_llm()
        response_text = await llm.chat(prompt)
        response_text = response_text.strip()

        # Handle markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        params = json.loads(response_text) if response_text else {}
        logger.debug(f"Extracted transform params: {params}")
        return params

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse transform params: {e}")
        return {}
    except Exception as e:
        logger.warning(f"Transform param extraction failed: {e}")
        return {}


async def draft_transform_node(state: AgentState) -> dict[str, Any]:
    """Handle DRAFT_TRANSFORM intent - structural mutations.

    Receives classified intent with transform_operation and applies
    the structural change to the StructuredDraft.

    Operations:
    - split_to_plan: Convert SINGLE_ITEM to PLAN
    - add_items: Add epics/stories to items list
    - merge_items: Combine multiple items
    - elevate_to_epic: Change item type to EPIC
    - decompose_to_stories: Create stories under an epic
    - change_scope: Switch SINGLE/EPICS_ONLY/FULL_PLAN
    - remove_items: Delete specific items

    Returns partial state update with:
    - structured_draft: Mutated draft
    - decision_result: Contains action="transform_applied" with result details
    """
    intent_result = state.get("intent_result", {})
    transform_op = intent_result.get("transform_operation")
    user_id = state.get("user_id", "unknown")

    # Get or create structured draft
    structured_draft = state.get("structured_draft")
    draft = state.get("draft")

    if structured_draft is None and draft is not None:
        # Migrate from legacy TicketDraft
        structured_draft = StructuredDraft.from_ticket_draft(draft, user_id)
        logger.info(
            f"Migrated TicketDraft to StructuredDraft: "
            f"lifecycle={structured_draft.lifecycle}"
        )
    elif structured_draft is None:
        # No draft at all - create empty
        structured_draft = StructuredDraft(created_by=user_id)

    # Extract transform parameters from intent (may be populated by LLM or future extraction)
    transform_params = intent_result.get("transform_params", {})

    # If no params provided, try to extract from message
    if not transform_params:
        # Get the latest message from state
        messages = state.get("messages", [])
        latest_message = ""
        for msg in reversed(messages):
            if hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, str):
                    latest_message = content
                    break

        if latest_message and transform_op:
            transform_params = await _extract_transform_params(
                message=latest_message,
                operation=transform_op,
                draft=structured_draft,
            )

    # Dispatch to appropriate mutation method
    mutation_result = _apply_transform(
        draft=structured_draft,
        operation=transform_op,
        user_id=user_id,
        params=transform_params,
    )

    logger.info(
        f"DRAFT_TRANSFORM: operation={transform_op}, "
        f"success={mutation_result.get('success')}, "
        f"draft_kind={structured_draft.kind}, lifecycle={structured_draft.lifecycle}"
    )

    return {
        "structured_draft": structured_draft,
        "decision_result": {
            "action": "transform_applied",
            "transform_result": mutation_result,
            "operation": transform_op,
            "reason": mutation_result.get("message", f"Transform: {transform_op}"),
        },
    }


def _apply_transform(
    draft: StructuredDraft,
    operation: str | None,
    user_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Apply a transform operation to the draft.

    Args:
        draft: The StructuredDraft to mutate
        operation: The transform operation name
        user_id: User making the change
        params: Additional parameters for the operation

    Returns:
        Dict with 'success', 'message', and operation-specific fields
    """
    if not operation:
        return {
            "success": False,
            "applied": False,
            "message": "No transform operation specified",
        }

    # Map operations to methods
    if operation == "split_to_plan":
        item_titles = params.get("item_titles", [])
        result = draft.split_to_plan(user_id, item_titles or None)

    elif operation == "add_items":
        items_to_add = params.get("items", [])
        result = draft.add_items(user_id, items_to_add)

    elif operation == "merge_items":
        item_ids = params.get("item_ids", [])
        merged_title = params.get("merged_title")
        result = draft.merge_items(user_id, item_ids, merged_title)

    elif operation == "elevate_to_epic":
        item_id = params.get("item_id")
        result = draft.elevate_to_epic(user_id, item_id)

    elif operation == "decompose_to_stories":
        epic_id = params.get("epic_id")
        story_titles = params.get("story_titles", [])
        result = draft.decompose_to_stories(user_id, epic_id, story_titles or None)

    elif operation == "change_scope":
        scope_str = params.get("scope", "").lower()
        scope_map = {
            "single": DraftScope.SINGLE,
            "epics_only": DraftScope.EPICS_ONLY,
            "full_plan": DraftScope.FULL_PLAN,
        }
        new_scope = scope_map.get(scope_str)
        if new_scope:
            result = draft.change_scope(user_id, new_scope)
        else:
            result = {"success": False, "message": f"Unknown scope: {scope_str}"}

    elif operation == "remove_items":
        item_ids = params.get("item_ids", [])
        result = draft.remove_items(user_id, item_ids)

    else:
        result = {
            "success": False,
            "message": f"Unknown transform operation: {operation}",
        }

    # Add applied flag for consistency
    result["applied"] = result.get("success", False)
    return result
