"""Mode dispatcher - routes classified intents to handlers.

Ref: BOT_DESIGN.md - Four SuperModes
"""

import logging
from functools import lru_cache

from src.domain.channel import ChannelAggregate
from src.domain.entities import Entity
from src.domain.types import ChannelId, EntityId
from src.intent.schemas import IntentClassification, SafetyCheckResult, SuperMode
from src.intent.safety import ActionContext, evaluate_safety
from src.modes.base import ModeContext, ModeHandler, ModeResult
from src.modes.converse import ConverseModeHandler
from src.modes.create import CreateModeHandler
from src.modes.modify import ModifyModeHandler
from src.modes.record import RecordModeHandler

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
        channel_aggregate: ChannelAggregate | None = None,
        target_entity: Entity | None = None,
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
            channel_aggregate: Channel aggregate for entity operations
            target_entity: Target entity for MODIFY mode

        Returns:
            ModeResult from the handler
        """
        # Run safety check
        safety_context = ActionContext(
            user_id=user_id,
            channel_id=channel_id,
            intent=intent,
            target_entity=target_entity,
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
            channel_aggregate=channel_aggregate,
            target_entity=target_entity,
        )

        # Get handler and dispatch
        handler = self.get_handler(intent.mode)
        result = await handler.handle(context)

        logger.info(
            f"Handler {handler.mode_name} returned: "
            f"requires_confirmation={result.requires_confirmation}, "
            f"entity_created={result.entity_created}"
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
