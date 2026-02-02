"""RECORD mode handler.

Handles capturing decisions from conversation.

Ref: BOT_DESIGN.md - RECORD Mode
"""

import logging

from src.modes.base import ModeHandler, ModeContext, ModeResult

logger = logging.getLogger(__name__)


class RecordModeHandler(ModeHandler):
    """Handler for RECORD mode.

    RECORD mode behavior (per BOT_DESIGN.md):
    1. Extract decision from context
    2. Infer decision type (ARCHITECTURE, SCOPE, CONSTRAINT, etc.)
    3. Create Decision entity
    4. Link to affected entities
    5. Post for approval

    This is a skeleton - full implementation in Phase 4 (Entity Lifecycle).
    """

    @property
    def mode_name(self) -> str:
        return "RECORD"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle RECORD mode message.

        For now, returns a placeholder response.
        Full implementation requires entity system from Phase 4.
        """
        logger.info(
            f"RECORD mode: user={context.user_id}, "
            f"confidence={context.intent.confidence}"
        )

        # Safety check
        if not context.safety_check.allowed:
            return ModeResult(
                response_text=f"Cannot record decision: {context.safety_check.reason}",
            )

        # Placeholder response
        return ModeResult(
            response_text=(
                f"I detected a decision in your message. "
                f"Decision recording will be available in Phase 4.\n\n"
                f"_Classification: {context.intent.reasoning}_"
            ),
            requires_confirmation=True,
            confirmation_data={
                "action": "record",
                "decision_text": context.message,
            },
        )
