"""Intent router: main entry points and LangGraph node.

This module contains the public API for intent classification:
- classify_intent: Main classification function
- classify_intent_with_context: Context-aware classification
- classify_intent_v2: Phase 39 router wrapper
- intent_router_node: LangGraph node for intent routing
- get_intent_classifier: Factory for classifier selection
- run_pre_gates: Pre-gate checks before classification

Part of the modularized intent package (Phase 42).
"""
import logging
from typing import Optional, TYPE_CHECKING

from src.schemas.intent import (
    Intent, IntentResult, SuperMode, get_super_mode,
    TaskPlanProposal, TaskProposal, has_multi_intent_markers,
)
from src.schemas.state import ReviewState

# Import from sibling modules
from src.graph.intent.pre_gates import (
    _detect_decision_type_hint,
    DECISION_TYPE_KEYWORDS,
)
from src.graph.intent.mode_classifier import _llm_classify
from src.graph.intent.intent_classifier import (
    _llm_classify_multi_intent,
    _generate_task_title,
    _extract_intent_params,
)
from src.graph.intent.policy import (
    should_use_multi_intent_classification,
    ACTION_VERBS,
)

if TYPE_CHECKING:
    from src.schemas.anchor import ThreadContext
    from src.schemas.state import AgentState

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
IntentType = Intent  # Alias for legacy code


async def classify_intent_with_context(
    message: str,
    thread_context: Optional["ThreadContext"],
    conversation_context: dict | None = None,
    active_draft: dict | None = None,
) -> IntentResult:
    """Classify intent with thread context awareness using LLM.

    Thread context (decision thread, workitem thread, etc.) is passed to the LLM
    for context-aware classification. No pattern matching is used.

    Args:
        message: User's message text.
        thread_context: Resolved thread context (from ContextResolver).
        conversation_context: Full conversation history.
        active_draft: Active draft summary for classification.

    Returns:
        IntentResult with intent type, confidence, and reasons.
    """
    # Pass thread context to LLM for context-aware classification
    return await _llm_classify(message, conversation_context, active_draft, thread_context)


async def classify_intent(
    message: str,
    conversation_context: dict | None = None,
    active_draft: dict | None = None,  # Phase 26
    return_proposal: bool = False,  # Phase 35: Return TaskPlanProposal for multi-intent
) -> IntentResult | TaskPlanProposal:
    """Classify user message intent using LLM only.

    All intent classification is done via LLM - no pattern matching.

    Phase 35: When return_proposal=True, returns TaskPlanProposal with multiple
    tasks for compound requests. Uses should_use_multi_intent_classification()
    to determine if multi-intent re-classification is needed.

    Args:
        message: User's message text
        conversation_context: Full conversation history for context
        active_draft: Active draft summary for context-aware classification (Phase 26)
        return_proposal: If True, return TaskPlanProposal (Phase 35)

    Returns:
        IntentResult for single intent, or TaskPlanProposal if return_proposal=True
    """
    # LLM-only classification (no pattern matching)
    single_result = await _llm_classify(message, conversation_context, active_draft)
    logger.info(
        f"Intent classified by LLM: {single_result.intent.value}, "
        f"confidence={single_result.confidence}, persona={single_result.persona_hint}, reasons={single_result.reasons}"
    )

    # Phase 35: Check if we should use multi-intent classification
    if return_proposal and should_use_multi_intent_classification(message, single_result):
        logger.info(
            f"Multi-intent re-classification triggered for message: "
            f"markers={has_multi_intent_markers(message)}, confidence={single_result.confidence}"
        )
        proposal = await _llm_classify_multi_intent(message, conversation_context, active_draft)
        return proposal

    if return_proposal:
        # Wrap single result in TaskPlanProposal
        return TaskPlanProposal(
            tasks=[TaskProposal(
                intent=single_result.intent,
                super_mode=single_result.super_mode or get_super_mode(single_result.intent),
                confidence=single_result.confidence,
                title=_generate_task_title(single_result),
                params=_extract_intent_params(single_result),
                depends_on_indices=[],
            )],
            is_multi_intent=False,
            low_confidence_signal=single_result.confidence < 0.7,
            trigger_message=message,
            reasons=single_result.reasons,
        )

    return single_result


async def intent_router_node(state: dict) -> dict:
    """LangGraph node for intent routing.

    Gets the latest human message and classifies intent using LLM with full context.
    After classification, resolves attachment context based on SuperMode policy.
    Returns partial state update with intent_result and attachment_context.

    Phase 35: When multi-intent is detected, stores TaskPlanProposal in intent_result
    for task_decomposer to use.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with intent_result and attachment_context
    """
    from langchain_core.messages import HumanMessage
    from src.slack.handlers.dispatch import resolve_attachment_context

    # Check if intent is already forced (e.g., from scope_gate selection or continuation detection)
    existing_intent = state.get("intent_result")
    if existing_intent:
        reasons = existing_intent.get("reasons", [])
        forced_patterns = ["scope_gate", "event_router", "continuation"]
        if any(pattern in r for r in reasons for pattern in forced_patterns):
            logger.info(f"Skipping intent classification - already forced: {existing_intent.get('intent')}, reasons={reasons}")
            return {"intent_result": existing_intent}

    # CRITICAL: Check for active review session BEFORE classification
    # If review is active, force REVIEW_CONTINUATION to prevent overwriting
    review_context = state.get("review_context")
    if review_context and review_context.get("state") in [ReviewState.ACTIVE, ReviewState.CONTINUATION]:
        logger.info(
            f"Active review detected, forcing REVIEW_CONTINUATION intent",
            extra={
                "review_topic": review_context.get("topic"),
                "review_state": review_context.get("state"),
            }
        )
        forced_result = IntentResult(
            intent=Intent.REVIEW_CONTINUATION,
            confidence=1.0,
            super_mode=SuperMode.THINK,
            reasons=["review_continuation: active review session detected"],
        )
        return {"intent_result": forced_result.model_dump()}

    # Get latest human message
    messages = state.get("messages", [])
    latest_human_message = None

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    if not latest_human_message:
        logger.warning("No human message found for intent classification")
        result = IntentResult(
            intent=Intent.REVIEW,
            confidence=0.5,
            super_mode=SuperMode.THINK,  # REVIEW maps to THINK
            reasons=["no message found, default to REVIEW"],
        )
        proposal = None
    else:
        # Get conversation context for LLM
        conversation_context = state.get("conversation_context")

        # Build active draft summary for context-aware classification (Phase 26)
        active_draft = None
        draft = state.get("draft")
        if draft and hasattr(draft, 'title') and draft.title:
            active_draft = {
                "title": draft.title,
                "issue_type": draft.issue_type.value if hasattr(draft, 'issue_type') and draft.issue_type else None,
                "requested_scope": draft.requested_scope.value if hasattr(draft, 'requested_scope') and draft.requested_scope else None,
            }

        # Phase 33-05: Use context-aware classification when thread_context available
        thread_context = state.get("thread_context")
        if thread_context:
            result = await classify_intent_with_context(
                latest_human_message,
                thread_context,
                conversation_context,
                active_draft,
            )
            proposal = None  # Context-aware doesn't support return_proposal yet
        else:
            # Phase 35: Use return_proposal=True to get TaskPlanProposal for multi-intent
            classification_result = await classify_intent(
                latest_human_message,
                conversation_context,
                active_draft,
                return_proposal=True,
            )

            # Handle both return types
            if isinstance(classification_result, TaskPlanProposal):
                proposal = classification_result
                result = proposal.to_single_intent()
            else:
                result = classification_result
                proposal = None

    logger.info(
        f"IntentRouter: intent={result.intent.value}, "
        f"confidence={result.confidence}, reasons={result.reasons}"
        f"{', multi_intent=True' if proposal and proposal.is_multi_intent else ''}"
    )

    # Phase 34: Resolve attachment context based on SuperMode policy
    # This populates state["attachment_context"] for downstream nodes
    intent_result_dict = result.model_dump()

    # Phase 35: Store TaskPlanProposal in intent_result for task_decomposer
    if proposal:
        intent_result_dict["task_plan_proposal"] = proposal.model_dump()
        # Set super_mode from proposal's primary mode
        intent_result_dict["super_mode"] = proposal.primary_mode.value

    state_update: dict = {"intent_result": intent_result_dict}

    # Store super_mode in state for downstream nodes (e.g., review node uses it for cite mode)
    state_update["super_mode"] = result.super_mode

    try:
        updated_state = await resolve_attachment_context(state, result.super_mode)
        if updated_state.get("attachment_context"):
            state_update["attachment_context"] = updated_state["attachment_context"]
            logger.debug(
                "Attachment context resolved in intent_router",
                extra={
                    "super_mode": result.super_mode.value,
                    "pinned_count": len(updated_state["attachment_context"].pinned),
                    "retrieved_count": len(updated_state["attachment_context"].retrieved_chunks),
                }
            )
    except Exception as e:
        logger.warning(f"Failed to resolve attachment context: {e}")
        # Non-blocking - continue without attachment context

    return state_update


# === Phase 39: New Intent Router Integration ===

async def classify_intent_v2(state: "AgentState") -> dict:
    """New intent classification using Phase 39 router.

    Wraps intent_router_node for gradual migration.
    Returns both new envelope and legacy IntentResult.
    """
    from src.graph.intent_router import intent_router_node as intent_router_node_v2

    result = await intent_router_node_v2(state)

    # Log migration metrics
    envelope = result.get("envelope")
    legacy = result.get("intent_result")

    if envelope and legacy:
        logger.info(
            f"Intent v2: envelope={envelope.kind.value}, "
            f"legacy={legacy.intent.value}, "
            f"match={envelope.intent == legacy.intent if envelope.intent else 'N/A'}"
        )

    return result


def get_intent_classifier(use_v2: bool = False):
    """Get intent classifier function.

    Args:
        use_v2: If True, use Phase 39 router. Default False for safety.

    Returns:
        Classifier function
    """
    if use_v2:
        return classify_intent_v2
    return intent_router_node  # Original


def run_pre_gates(message: str) -> Optional[str]:
    """Run pre-gate checks on message before LLM classification.

    Currently detects decision type hints from keywords.

    Args:
        message: User's message text

    Returns:
        Decision type hint if detected, None otherwise
    """
    return _detect_decision_type_hint(message)
