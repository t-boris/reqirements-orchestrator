"""MODIFY mode handler.

Handles modifications to existing entities.

Ref: BOT_DESIGN.md - MODIFY Mode
"""

import logging

from src.modes.base import ModeHandler, ModeContext, ModeResult

logger = logging.getLogger(__name__)


class ModifyModeHandler(ModeHandler):
    """Handler for MODIFY mode.

    MODIFY mode behavior (per BOT_DESIGN.md):
    1. Identify target entity
    2. Validate lifecycle allows modification (Draft or Proposed only)
    3. Apply changes
    4. Emit EntityUpdated event
    5. Update canonical message

    This is a skeleton - full implementation in Phase 4 (Entity Lifecycle).
    """

    @property
    def mode_name(self) -> str:
        return "MODIFY"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle MODIFY mode message.

        For now, returns a placeholder response.
        Full implementation requires entity system from Phase 4.
        """
        logger.info(
            f"MODIFY mode: user={context.user_id}, "
            f"target_entity={context.intent.target_entity_id}"
        )

        # Safety check
        if not context.safety_check.allowed:
            return ModeResult(
                response_text=f"Cannot modify: {context.safety_check.reason}",
            )

        # Placeholder response
        target = context.intent.target_entity_id or "entity"
        return ModeResult(
            response_text=(
                f"I understand you want to modify {target}. "
                f"Entity modification will be available in Phase 4.\n\n"
                f"_Classification: {context.intent.reasoning}_"
            ),
            requires_confirmation=True,
            confirmation_data={
                "action": "modify",
                "target_entity_id": context.intent.target_entity_id,
                "source_message": context.message,
            },
        )
