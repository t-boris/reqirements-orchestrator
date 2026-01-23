"""Draft Transform node - handles structural mutations of StructuredDraft.

Routes from DRAFT_TRANSFORM intent. Mutates draft structure based on
transform_operation and returns to decision flow for validation.

Phase 28 requirement R4: New intent DRAFT_TRANSFORM.
"""
import logging
from typing import Any

from src.schemas.state import AgentState
from src.schemas.structured_draft import StructuredDraft

logger = logging.getLogger(__name__)


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
    - decision_result: Contains action="transform_applied" for handler
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

    # Apply transformation based on operation
    # Note: Actual mutation logic will be implemented in Phase 28.3
    # For now, we prepare the state and log the intent

    transform_result = {
        "operation": transform_op,
        "applied": False,  # Will be True after 28.3 implements mutations
        "message": (
            f"Transform operation '{transform_op}' recognized. "
            f"Mutation engine pending (Phase 28.3)."
        ),
    }

    # Log the transformation request
    structured_draft.log_change(
        action=f"transform_requested:{transform_op}",
        user_id=user_id,
        details={"operation": transform_op, "intent_result": intent_result},
    )

    logger.info(
        f"DRAFT_TRANSFORM: operation={transform_op}, "
        f"draft_kind={structured_draft.kind}, lifecycle={structured_draft.lifecycle}"
    )

    return {
        "structured_draft": structured_draft,
        "decision_result": {
            "action": "transform_applied",
            "transform_result": transform_result,
            "reason": f"Structural transform requested: {transform_op}",
        },
    }
