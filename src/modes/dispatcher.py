"""Mode dispatcher - routes classified intents to handlers.

Ref: BOT_DESIGN.md - Four SuperModes
"""

import logging
from functools import lru_cache

from src.intent.schemas import SuperMode, IntentClassification, SafetyCheckResult
from src.intent.safety import ActionContext, evaluate_safety
from src.modes.base import ModeHandler, ModeContext, ModeResult
from src.modes.create import CreateModeHandler
from src.modes.modify import ModifyModeHandler
from src.modes.record import RecordModeHandler
from src.modes.converse import ConverseModeHandler

logger = logging.getLogger(__name__)


class ModeDispatcher:
    """Dispatches classified intents to appropriate mode handlers."""

    def __init__(self):
        self._handlers: dict[SuperMode, ModeHandler] = {
            SuperMode.CREATE: CreateModeHandler(),
            SuperMode.MODIFY: ModifyModeHandler(),
            SuperMode.RECORD: RecordModeHandler(),
            SuperMode.CONVERSE: ConverseModeHandler(),
        }

    def get_handler(self, mode: SuperMode) -> ModeHandler:
        """Get the handler for a mode."""
        return self._handlers[mode]

    async def dispatch(
        self,
        message: str,
        user_id: str,
        channel_id: str,
        thread_ts: str | None,
        intent: IntentClassification,
        *,
        thread_messages: list[dict] | None = None,
        entity_data: dict | None = None,
    ) -> ModeResult:
        """Dispatch an intent to the appropriate handler.

        Args:
            message: Original message text
            user_id: User who sent the message
            channel_id: Channel ID
            thread_ts: Thread timestamp (if in thread)
            intent: Classified intent from router
            thread_messages: Thread context (optional)
            entity_data: Target entity data for MODIFY (optional)

        Returns:
            ModeResult from the handler
        """
        # Run safety check
        safety_context = ActionContext(
            user_id=user_id,
            channel_id=channel_id,
            intent=intent,
            target_entity=None,  # Will be populated in Phase 4
        )
        safety_result = evaluate_safety(safety_context)

        logger.info(
            f"Dispatching: mode={intent.mode}, "
            f"confidence={intent.confidence:.2f}, "
            f"safety_allowed={safety_result.allowed}"
        )

        # Build context
        context = ModeContext(
            message=message,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            intent=intent,
            safety_check=safety_result,
            thread_messages=thread_messages or [],
            entity_data=entity_data,
        )

        # Get handler and dispatch
        handler = self.get_handler(intent.mode)
        result = await handler.handle(context)

        logger.info(
            f"Handler {handler.mode_name} returned: "
            f"requires_confirmation={result.requires_confirmation}"
        )

        return result


# Module-level dispatcher instance
_dispatcher: ModeDispatcher | None = None


@lru_cache
def get_dispatcher() -> ModeDispatcher:
    """Get the mode dispatcher instance."""
    return ModeDispatcher()


async def dispatch_mode(
    message: str,
    user_id: str,
    channel_id: str,
    thread_ts: str | None,
    intent: IntentClassification,
    **kwargs,
) -> ModeResult:
    """Convenience function to dispatch an intent.

    See ModeDispatcher.dispatch for full documentation.
    """
    dispatcher = get_dispatcher()
    return await dispatcher.dispatch(
        message=message,
        user_id=user_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        intent=intent,
        **kwargs,
    )
