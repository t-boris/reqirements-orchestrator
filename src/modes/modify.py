"""MODIFY mode handler - modifies existing entities.

Ref: BOT_DESIGN.md - MODIFY Mode
"""

import logging

from src.domain.channel import ChannelAggregate, InvalidStateError
from src.domain.entities import DraftEntity, ProposedEntity
from src.domain.transitions import can_modify
from src.domain.types import ChannelId, EntityId, UserId
from src.modes.base import ModeContext, ModeHandler, ModeResult

logger = logging.getLogger(__name__)


class ModifyModeHandler(ModeHandler):
    """Handler for MODIFY mode - modifies existing entities."""

    @property
    def mode_name(self) -> str:
        return "MODIFY"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle MODIFY mode - update an existing entity.

        Flow:
        1. Check safety (modification allowed?)
        2. Find target entity
        3. Validate entity state allows modification
        4. Apply changes
        5. Return updated entity
        """
        # Safety check
        if not context.safety_check.allowed:
            return ModeResult(
                response_text=context.safety_check.reason or "Modification not allowed",
            )

        # Get target entity
        target_entity_id = context.intent.target_entity_id
        if not target_entity_id:
            return ModeResult(
                response_text="I couldn't identify which entity you want to modify. Please be more specific or mention the entity by name.",
            )

        # Check if we have the aggregate
        if not context.channel_aggregate:
            # In production, load from event store
            return ModeResult(
                response_text="Entity modification requires channel context. This will be available once the event store integration is complete.",
            )

        aggregate = context.channel_aggregate
        entity = aggregate.get_entity(EntityId(target_entity_id))

        if not entity:
            return ModeResult(
                response_text=f"Entity {target_entity_id} not found in this channel.",
            )

        # Check if entity can be modified
        can_mod, reason = can_modify(entity)
        if not can_mod:
            return ModeResult(
                response_text=f"Cannot modify this entity: {reason}",
            )

        # For now, return placeholder
        # Full implementation will extract changes from message and apply them
        entity_type = "work item" if hasattr(entity.content, "issue_type") else "decision"

        return ModeResult(
            response_text=f"I understand you want to modify the {entity_type}. What changes would you like to make?",
            entity_modified=target_entity_id,
            requires_confirmation=True,
            confirmation_data={
                "action": "modify_entity",
                "entity_id": target_entity_id,
                "current_state": type(entity).__name__,
            },
        )
