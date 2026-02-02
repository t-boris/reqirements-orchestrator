"""CREATE mode handler.

Handles creation of new work items and decisions.

Ref: BOT_DESIGN.md - CREATE Mode
"""

import logging

from src.modes.base import ModeHandler, ModeContext, ModeResult

logger = logging.getLogger(__name__)


class CreateModeHandler(ModeHandler):
    """Handler for CREATE mode.

    CREATE mode behavior (per BOT_DESIGN.md):
    1. Extract structured content from conversation
    2. Create Draft entity
    3. Post formatted preview
    4. Offer "Propose to channel" button

    This is a skeleton - full implementation in Phase 4 (Entity Lifecycle).
    """

    @property
    def mode_name(self) -> str:
        return "CREATE"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle CREATE mode message.

        For now, returns a placeholder response.
        Full implementation requires entity system from Phase 4.
        """
        logger.info(
            f"CREATE mode: user={context.user_id}, "
            f"entity_type={context.intent.entity_type}"
        )

        # Safety check should require confirmation
        if not context.safety_check.allowed:
            return ModeResult(
                response_text=f"Cannot create: {context.safety_check.reason}",
            )

        # Placeholder response - actual extraction and entity creation in Phase 4
        entity_type = context.intent.entity_type or "item"
        return ModeResult(
            response_text=(
                f"I understand you want to create a new {entity_type.value if hasattr(entity_type, 'value') else entity_type}. "
                f"Entity creation will be available in Phase 4.\n\n"
                f"_Classification: {context.intent.reasoning}_"
            ),
            requires_confirmation=True,
            confirmation_data={
                "action": "create",
                "entity_type": str(entity_type),
                "source_message": context.message,
            },
        )
