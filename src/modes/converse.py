"""CONVERSE mode handler.

Handles casual conversation, questions, and clarifications.

Ref: BOT_DESIGN.md - CONVERSE Mode
"""

import logging

from src.modes.base import ModeHandler, ModeContext, ModeResult

logger = logging.getLogger(__name__)


class ConverseModeHandler(ModeHandler):
    """Handler for CONVERSE mode.

    CONVERSE mode behavior (per BOT_DESIGN.md):
    1. Respond helpfully
    2. DO NOT create entities
    3. DO NOT emit events (except maybe MessageReceived for audit)
    4. Maintain context for future intent detection

    This is the safe fallback mode - no side effects.
    """

    @property
    def mode_name(self) -> str:
        return "CONVERSE"

    async def handle(self, context: ModeContext) -> ModeResult:
        """Handle CONVERSE mode message.

        CONVERSE is the safe mode - no side effects, just helpful response.
        In Phase 5+ this will use LLM for contextual responses.
        """
        logger.info(
            f"CONVERSE mode: user={context.user_id}, "
            f"confidence={context.intent.confidence}"
        )

        # For now, acknowledge and explain
        # Phase 5+ will add LLM-powered contextual responses
        response = self._generate_response(context)

        return ModeResult(
            response_text=response,
            requires_confirmation=False,  # CONVERSE never needs confirmation
        )

    def _generate_response(self, context: ModeContext) -> str:
        """Generate a helpful response.

        For now, simple acknowledgment. Will be enhanced in later phases.
        """
        # Check if this was a fallback from low confidence
        if context.intent.confidence < 0.7:
            return (
                "I'm not sure what you'd like me to do. "
                "Could you clarify? You can:\n"
                "- Ask me to *create* a work item or decision\n"
                "- *Modify* an existing item\n"
                "- *Record* a decision you've made\n"
                "- Just chat to explore ideas"
            )

        # Check if from a pregate
        if "pregate" in context.intent.reasoning.lower():
            # Handled by pregates, just acknowledge
            return f"Got it. {context.intent.reasoning}"

        # Normal conversation
        return (
            "I understand you're exploring or discussing. "
            "Let me know when you're ready to create something or record a decision!"
        )
