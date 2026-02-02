"""LLM Router - Intent classification using structured output.

Ref: RESEARCH.md - Pattern 2: Structured LLM Classification with Instructor
Ref: RESEARCH.md - Pattern 3: Confidence Threshold with Safe Fallback
Ref: BOT_DESIGN.md - Stage 2: LLM Router
"""

import logging
from dataclasses import dataclass

from src.config import get_settings
from src.intent.schemas import (
    SuperMode,
    IntentClassification,
    PreGateResult,
    PreGateOutput,
)
from src.intent.pregates import check_pregates
from src.intent.prompts import INTENT_CLASSIFICATION_SYSTEM, INTENT_CLASSIFICATION_USER
from src.llm.client import structured_completion

logger = logging.getLogger(__name__)

# Confidence thresholds
# Ref: RESEARCH.md - Pattern 3: Confidence Threshold with Safe Fallback
CONFIDENCE_THRESHOLD_BASE = 0.7      # Below this -> CONVERSE
CONFIDENCE_THRESHOLD_SIDE_EFFECT = 0.85  # CREATE/MODIFY require higher confidence


@dataclass
class RouterContext:
    """Context for intent routing."""

    channel_id: str
    channel_name: str
    thread_ts: str | None
    thread_summary: str
    entity_summaries: str
    active_process_threads: set[str]


async def classify_intent(
    message: str,
    event_type: str,
    context: RouterContext,
    *,
    bot_id: str | None = None,
    message_bot_id: str | None = None,
) -> IntentClassification:
    """Classify message intent using two-stage routing.

    Stage 1: PreGates (deterministic)
    Stage 2: LLM Router (if PreGates pass through)

    Args:
        message: Message text
        event_type: Slack event type
        context: Router context with channel/thread info
        bot_id: Our bot's ID
        message_bot_id: Bot ID from the message (if from a bot)

    Returns:
        IntentClassification with mode, confidence, and reasoning

    Ref: BOT_DESIGN.md - Two-Stage Intent Classification
    """
    # Stage 1: PreGates
    pregate_result = check_pregates(
        message=message,
        event_type=event_type,
        bot_id=bot_id,
        message_bot_id=message_bot_id,
        thread_ts=context.thread_ts,
        active_process_threads=context.active_process_threads,
    )

    # Handle deterministic routing
    if pregate_result.result != PreGateResult.PASS_THROUGH:
        return _pregate_to_classification(pregate_result)

    # Stage 2: LLM Router
    return await _llm_classify(message, context)


def _pregate_to_classification(pregate: PreGateOutput) -> IntentClassification:
    """Convert PreGate result to IntentClassification.

    PreGate results map to modes with 1.0 confidence since they're deterministic.
    """
    match pregate.result:
        case PreGateResult.BOT_MESSAGE:
            # Bot messages should be ignored - return CONVERSE with note
            return IntentClassification(
                mode=SuperMode.CONVERSE,
                confidence=1.0,
                reasoning="Bot message - ignored",
            )
        case PreGateResult.COMMAND:
            # Commands are handled separately, return CONVERSE as placeholder
            return IntentClassification(
                mode=SuperMode.CONVERSE,
                confidence=1.0,
                reasoning=f"Slash command: {pregate.data}",
            )
        case PreGateResult.ACTION:
            # Actions are handled by action handlers
            return IntentClassification(
                mode=SuperMode.CONVERSE,
                confidence=1.0,
                reasoning="Button action - handled by action handler",
            )
        case PreGateResult.APPROVAL:
            # Approvals map to MODIFY (changing entity state)
            action = pregate.data.get("action", "approve") if pregate.data else "approve"
            return IntentClassification(
                mode=SuperMode.MODIFY,
                confidence=1.0,
                reasoning=f"Explicit {action} keyword detected",
            )
        case PreGateResult.PROCESS:
            # Process messages are handled by process executor
            return IntentClassification(
                mode=SuperMode.CONVERSE,
                confidence=1.0,
                reasoning=f"Active process thread: {pregate.data}",
            )
        case _:
            # Fallback (should not happen)
            return IntentClassification(
                mode=SuperMode.CONVERSE,
                confidence=0.0,
                reasoning="Unknown pregate result",
            )


async def _llm_classify(message: str, context: RouterContext) -> IntentClassification:
    """Classify intent using LLM with structured output.

    Ref: RESEARCH.md - Pattern 2: Structured LLM Classification
    """
    # Build prompt
    user_prompt = INTENT_CLASSIFICATION_USER.format(
        channel_name=context.channel_name,
        thread_summary=context.thread_summary or "No thread context",
        entity_summaries=context.entity_summaries or "No existing entities",
        message_text=message,
    )

    try:
        result = await structured_completion(
            response_model=IntentClassification,
            messages=[
                {"role": "system", "content": INTENT_CLASSIFICATION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )

        # Apply confidence thresholds
        return _apply_confidence_thresholds(result)

    except Exception as e:
        logger.warning(f"LLM classification failed: {e}, falling back to CONVERSE")
        return IntentClassification(
            mode=SuperMode.CONVERSE,
            confidence=0.0,
            reasoning=f"Classification failed: {e}",
        )


def _apply_confidence_thresholds(result: IntentClassification) -> IntentClassification:
    """Apply confidence thresholds with safe fallback.

    Ref: RESEARCH.md - Pattern 3: Confidence Threshold with Safe Fallback
    Ref: CONTEXT.md - Safe defaults

    Rules:
    - confidence < 0.7 -> CONVERSE (too uncertain)
    - CREATE/MODIFY with confidence < 0.85 -> CONVERSE (side-effects need higher bar)
    """
    # Below base threshold - always fallback
    if result.confidence < CONFIDENCE_THRESHOLD_BASE:
        logger.info(
            f"Low confidence ({result.confidence:.2f} < {CONFIDENCE_THRESHOLD_BASE}), "
            f"falling back to CONVERSE from {result.mode}"
        )
        return IntentClassification(
            mode=SuperMode.CONVERSE,
            confidence=result.confidence,
            entity_type=result.entity_type,
            target_entity_id=result.target_entity_id,
            reasoning=f"Low confidence fallback. Original: {result.mode} - {result.reasoning}",
            entities_mentioned=result.entities_mentioned,
        )

    # Side-effect modes need higher confidence
    if result.mode in (SuperMode.CREATE, SuperMode.MODIFY):
        if result.confidence < CONFIDENCE_THRESHOLD_SIDE_EFFECT:
            logger.info(
                f"Side-effect mode {result.mode} with medium confidence "
                f"({result.confidence:.2f} < {CONFIDENCE_THRESHOLD_SIDE_EFFECT}), "
                f"falling back to CONVERSE"
            )
            return IntentClassification(
                mode=SuperMode.CONVERSE,
                confidence=result.confidence,
                entity_type=result.entity_type,
                target_entity_id=result.target_entity_id,
                reasoning=f"Medium confidence for side-effect mode. Original: {result.mode} - {result.reasoning}",
                entities_mentioned=result.entities_mentioned,
            )

    return result
