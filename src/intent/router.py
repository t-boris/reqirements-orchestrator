"""LLM Router - Intent classification using structured output.

Ref: RESEARCH.md - Pattern 2: Structured LLM Classification with Instructor
Ref: RESEARCH.md - Pattern 3: Confidence Threshold with Safe Fallback
Ref: BOT_DESIGN.md - Stage 2: LLM Router
"""

import logging
import time
from dataclasses import dataclass

from src.config import get_settings
from src.infrastructure.audit_log import IntentAuditEntry, log_intent_audit
from src.intent.schemas import (
    SuperMode,
    IntentClassification,
    PreGateResult,
    PreGateOutput,
    ExecutionPlan,
    PlanStep,
)
from src.intent.pregates import check_pregates
from src.intent.postfilters import apply_postfilters
from src.intent.prompts import INTENT_CLASSIFICATION_SYSTEM, INTENT_CLASSIFICATION_USER
from src.llm.client import structured_completion

logger = logging.getLogger(__name__)

# Confidence thresholds
# Ref: RESEARCH.md - Pattern 3: Confidence Threshold with Safe Fallback
CONFIDENCE_THRESHOLD_BASE = 0.6      # Below this -> CONVERSE
CONFIDENCE_THRESHOLD_SIDE_EFFECT = 0.75  # CREATE/MODIFY require higher confidence


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
    Stage 3: Post-filters (validate entity references)

    Every classification is audit-logged for debugging (fire-and-forget).

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
    start_ms = int(time.time() * 1000)

    # Stage 1: PreGates
    pregate_result = check_pregates(
        message=message,
        event_type=event_type,
        bot_id=bot_id,
        message_bot_id=message_bot_id,
        thread_ts=context.thread_ts,
        active_process_threads=context.active_process_threads,
    )

    pregate_result_str = (
        pregate_result.result.value
        if pregate_result.result != PreGateResult.PASS_THROUGH
        else None
    )
    pregate_data = pregate_result.data

    # Handle deterministic routing
    if pregate_result.result != PreGateResult.PASS_THROUGH:
        result = _pregate_to_classification(pregate_result)
        elapsed_ms = int(time.time() * 1000) - start_ms

        log_intent_audit(IntentAuditEntry(
            channel_id=context.channel_id,
            thread_ts=context.thread_ts,
            message_text=message[:500],
            pregate_result=pregate_result_str,
            pregate_data=pregate_data,
            raw_mode=result.mode.value,
            raw_confidence=result.confidence,
            classified_mode=result.mode.value,
            classified_confidence=result.confidence,
            entity_type=result.entity_type.value if result.entity_type else None,
            target_entity_id=result.target_entity_id,
            entities_mentioned=result.entities_mentioned,
            reasoning=result.reasoning,
            classification_ms=elapsed_ms,
        ))
        return result

    # Stage 2: LLM Router (returns raw result before threshold adjustment)
    raw_result = await _llm_classify_raw(message, context)

    # Apply confidence thresholds (raw -> classified)
    result = _apply_confidence_thresholds(raw_result)

    # Stage 3: Post-filters (validate entity references)
    result = await apply_postfilters(result, context.channel_id)

    elapsed_ms = int(time.time() * 1000) - start_ms

    # Log with both raw and final classification
    log_intent_audit(IntentAuditEntry(
        channel_id=context.channel_id,
        thread_ts=context.thread_ts,
        message_text=message[:500],
        pregate_result=pregate_result_str,
        pregate_data=pregate_data,
        raw_mode=raw_result.mode.value,
        raw_confidence=raw_result.confidence,
        classified_mode=result.mode.value,
        classified_confidence=result.confidence,
        entity_type=result.entity_type.value if result.entity_type else None,
        target_entity_id=result.target_entity_id,
        entities_mentioned=result.entities_mentioned,
        reasoning=result.reasoning,
        classification_ms=elapsed_ms,
    ))

    return result


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


async def _llm_classify_raw(message: str, context: RouterContext) -> IntentClassification:
    """Classify intent using LLM with structured output.

    Returns the raw LLM result BEFORE confidence threshold adjustment.
    Callers should apply _apply_confidence_thresholds() separately.

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

        # Return raw result without threshold adjustment
        return result

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
            is_compound_request=result.is_compound_request,
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
                is_compound_request=result.is_compound_request,
            )

    return result


def generate_execution_plan(
    intent: IntentClassification,
    message: str,
) -> ExecutionPlan | None:
    """Generate an execution plan for compound requests.

    When is_compound_request is True, creates a multi-step plan based on
    the detected pattern. Returns None for simple (non-compound) requests.

    Common patterns:
    - "analyze X and create Y" → ARCHITECT → CREATE (batch work items)
    - "review X and record Y" → ARCHITECT → CREATE (decisions)
    """
    if not intent.is_compound_request:
        return None

    # Determine the final action based on keywords in message
    message_lower = message.lower()

    # Detect what the user wants to create at the end
    wants_work_items = any(kw in message_lower for kw in [
        "work item", "epic", "story", "task", "ticket", "spike",
        "split into", "break down", "decompose",
    ])
    wants_decisions = any(kw in message_lower for kw in [
        "decision", "adr", "record", "document",
    ])

    steps: list[PlanStep] = []

    # Step 1: Analysis phase (ARCHITECT)
    if intent.mode == SuperMode.ARCHITECT or "analyze" in message_lower or "review" in message_lower:
        steps.append(PlanStep(
            mode=SuperMode.ARCHITECT,
            instruction="Analyze the existing decisions and architecture in this channel. "
                       "Identify key components, patterns, and areas that need implementation work.",
            pass_output_to_next=True,
        ))

    # Step 2: Creation phase
    if wants_work_items:
        steps.append(PlanStep(
            mode=SuperMode.CREATE,
            instruction="Based on the analysis, create multiple work items (epics/stories/tasks) "
                       "that cover the implementation. Each work item should be specific and actionable.",
            pass_output_to_next=False,
        ))
    elif wants_decisions:
        steps.append(PlanStep(
            mode=SuperMode.CREATE,
            instruction="Based on the analysis, create decision records (ADRs) for the key "
                       "architectural choices identified.",
            pass_output_to_next=False,
        ))
    else:
        # Default: create work items
        steps.append(PlanStep(
            mode=SuperMode.CREATE,
            instruction="Based on the analysis, create appropriate artifacts "
                       "(work items or decisions) as needed.",
            pass_output_to_next=False,
        ))

    # Only return a plan if we have multiple steps
    if len(steps) < 2:
        return None

    logger.info(f"Generated execution plan with {len(steps)} steps for compound request")

    return ExecutionPlan(
        steps=steps,
        reasoning=f"Compound request detected: {intent.reasoning}. "
                 f"Plan: {' → '.join(s.mode.value.upper() for s in steps)}",
    )
