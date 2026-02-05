"""Mode dispatcher - routes classified intents to handlers.

Ref: BOT_DESIGN.md - Six SuperModes
"""

import logging
from functools import lru_cache

from src.domain.channel import ChannelAggregate
from src.domain.entities import Entity
from src.domain.types import ChannelId, EntityId
from src.intent.schemas import IntentClassification, SafetyCheckResult, SuperMode, ExecutionPlan
from src.intent.safety import ActionContext, evaluate_safety
from src.intent.router import generate_execution_plan
from src.modes.base import ModeContext, ModeHandler, ModeResult
from src.modes.architect import ArchitectModeHandler
from src.modes.converse import ConverseModeHandler
from src.modes.create import CreateModeHandler
from src.modes.jira_mode import JiraModeHandler
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
            SuperMode.JIRA: JiraModeHandler(),
            SuperMode.ARCHITECT: ArchitectModeHandler(),
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

        For compound requests (is_compound_request=True), generates and executes
        a multi-step plan instead of a single mode dispatch.

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
            ModeResult from the handler (or aggregated from plan execution)
        """
        # Check for compound request and generate plan
        if intent.is_compound_request:
            plan = generate_execution_plan(intent, message)
            if plan:
                logger.info(
                    f"Compound request detected. Executing plan: "
                    f"{' → '.join(s.mode.value for s in plan.steps)}"
                )
                return await self._execute_plan(
                    plan=plan,
                    message=message,
                    user_id=user_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    intent=intent,
                    thread_messages=thread_messages,
                    entity_data=entity_data,
                    channel_aggregate=channel_aggregate,
                    target_entity=target_entity,
                )

        # Standard single-mode dispatch
        return await self._dispatch_single(
            message=message,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            intent=intent,
            thread_messages=thread_messages,
            entity_data=entity_data,
            channel_aggregate=channel_aggregate,
            target_entity=target_entity,
        )

    async def _dispatch_single(
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
        plan_step_context: str | None = None,
        is_plan_step: bool = False,
    ) -> ModeResult:
        """Execute a single mode dispatch."""
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
            f"{' (plan step)' if is_plan_step else ''}"
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
            plan_step_context=plan_step_context,
            is_plan_step=is_plan_step,
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

    async def _execute_plan(
        self,
        plan: ExecutionPlan,
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
        """Execute a multi-step plan.

        Steps are executed sequentially. Each step's output can be passed
        as additional context to the next step.
        """
        step_outputs: list[str] = []
        final_result: ModeResult | None = None

        for i, step in enumerate(plan.steps):
            logger.info(f"Executing plan step {i+1}/{len(plan.steps)}: {step.mode.value}")

            # Build plan context from previous steps
            plan_step_context: str | None = None
            if step_outputs and i > 0:
                plan_step_context = "\n\n".join(step_outputs)

            # Create a step-specific intent with entity_type for CREATE steps
            entity_type = intent.entity_type
            if step.mode == SuperMode.CREATE and "work item" in step.instruction.lower():
                from src.intent.schemas import EntityType
                entity_type = EntityType.WORK_ITEM

            step_intent = IntentClassification(
                mode=step.mode,
                confidence=intent.confidence,
                entity_type=entity_type,
                reasoning=f"Plan step {i+1}: {step.instruction}",
                entities_mentioned=intent.entities_mentioned,
                is_compound_request=False,  # Prevent recursion
            )

            # Execute the step
            result = await self._dispatch_single(
                message=message,  # Original message
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                intent=step_intent,
                thread_messages=thread_messages,
                entity_data=entity_data,
                channel_aggregate=channel_aggregate,
                target_entity=target_entity,
                plan_step_context=plan_step_context,
                is_plan_step=True,
            )

            # Capture output if needed for next step
            if step.pass_output_to_next and result.response_text:
                step_outputs.append(result.response_text)

            final_result = result

            # If a step requires confirmation, return early
            # The plan will need to be resumed after user confirms
            if result.requires_confirmation:
                logger.info(f"Plan paused at step {i+1} - requires confirmation")
                return result

        # Return the final step's result
        if final_result:
            return final_result

        # Fallback (shouldn't happen)
        return ModeResult(
            response_text="Plan execution completed but produced no output.",
        )


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
