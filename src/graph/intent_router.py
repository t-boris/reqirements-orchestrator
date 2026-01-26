"""Unified intent router (Phase 39).

Orchestrates:
- Stage 0: Deterministic pre-gates
- Stage 1: Mode classification
- Stage 2: Intent extraction
- Policy: Ambiguity/risk guards

Single entry point for intent classification.
"""
import logging
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

from src.schemas.intent import Intent, SuperMode
from src.schemas.intent_envelope import (
    IntentEnvelope,
    EnvelopeKind,
    RiskLevel,
)
from src.graph.intent_gates import (
    run_pre_gates,
    GateResult,
    PreGateOutput,
)
from src.graph.intent_stage1 import (
    classify_mode,
    build_context_hint,
    Stage1Result,
)
from src.graph.intent_stage2 import (
    classify_intent,
    build_target_hints,
)
from src.graph.intent_policy import (
    apply_all_policies,
    PolicyConfig,
)

if TYPE_CHECKING:
    from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


@dataclass
class RouterInput:
    """Input for intent router."""
    message: str
    channel_id: str
    thread_ts: Optional[str] = None
    user_id: Optional[str] = None
    is_command: bool = False
    command_name: Optional[str] = None
    state: Optional[dict] = None


@dataclass
class RouterResult:
    """Result from intent router."""
    envelope: IntentEnvelope
    stage0_gate: Optional[PreGateOutput] = None
    stage1_result: Optional[Stage1Result] = None
    bypassed: bool = False
    bypass_reason: Optional[str] = None


async def route_intent(
    input: RouterInput,
    context: str = "",
    policy_config: PolicyConfig = None,
) -> RouterResult:
    """Route user message through intent classification pipeline.

    Pipeline:
    1. Stage 0: Pre-gates (may bypass)
    2. Stage 1: Mode classification
    3. Stage 2: Intent extraction
    4. Policy: Ambiguity/risk checks

    Args:
        input: Router input with message and state
        context: Context string for LLM
        policy_config: Optional policy configuration

    Returns:
        RouterResult with envelope and pipeline metadata
    """
    state = input.state or {}
    config = policy_config or PolicyConfig()

    # === Stage 0: Pre-gates ===
    gate_output = run_pre_gates(
        message=input.message,
        state=state,
        is_command=input.is_command,
        command_name=input.command_name,
        thread_ts=input.thread_ts,
    )

    # Handle bypass
    if gate_output.result == GateResult.BYPASS:
        logger.info(f"Stage 0 bypass: {gate_output.bypass_reason}")
        envelope = _create_bypass_envelope(gate_output)
        return RouterResult(
            envelope=envelope,
            stage0_gate=gate_output,
            bypassed=True,
            bypass_reason=gate_output.bypass_reason,
        )

    # === Stage 1: Mode classification ===
    context_hint = build_context_hint(
        has_draft=bool(state.get("draft") or state.get("structured_draft")),
        has_taskplan=bool(state.get("task_plan")),
        anchor_type=_get_anchor_type(state),
    )

    stage1 = await classify_mode(input.message, context_hint)
    logger.info(
        f"Stage 1: mode={stage1.top_mode.value}, "
        f"score={stage1.top_score:.2f}, margin={stage1.margin:.2f}"
    )

    # Apply Stage 0 constraints
    if gate_output.result == GateResult.CONSTRAIN:
        stage1 = _apply_constraint(stage1, gate_output)

    # === Stage 2: Intent extraction ===
    anchor_type = _get_anchor_type(state)
    anchor_id = _get_anchor_id(state)

    envelope = await classify_intent(
        message=input.message,
        stage1=stage1,
        context=context,
        has_draft=bool(state.get("draft") or state.get("structured_draft")),
        anchor_type=anchor_type,
        anchor_id=anchor_id,
    )

    logger.info(
        f"Stage 2: kind={envelope.kind.value}, "
        f"intent={envelope.intent.value if envelope.intent else 'N/A'}, "
        f"confidence={envelope.confidence:.2f}"
    )

    # === Policy application ===
    envelope = apply_all_policies(envelope, config)

    if envelope.kind == EnvelopeKind.AMBIGUOUS:
        logger.info(f"Policy: converted to ambiguous - {envelope.reason}")

    return RouterResult(
        envelope=envelope,
        stage0_gate=gate_output,
        stage1_result=stage1,
    )


def _create_bypass_envelope(gate: PreGateOutput) -> IntentEnvelope:
    """Create envelope from Stage 0 bypass."""
    mode = SuperMode(gate.bypass_mode) if gate.bypass_mode else SuperMode.CHAT

    # Map bypass intent to Intent enum
    intent_map = {
        "meta": Intent.META,
        "ops": Intent.META,
        "sync_request": Intent.SYNC_REQUEST,
        "answer_mapper": Intent.DRAFT_REFINE,  # TaskPlan answer
        "discussion": Intent.DISCUSSION,
    }
    intent = intent_map.get(gate.bypass_intent, Intent.DISCUSSION)

    return IntentEnvelope.single(
        mode=mode,
        intent=intent,
        confidence=1.0,  # Deterministic
        margin=1.0,
        risk_level=RiskLevel.SAFE,
        reason=gate.bypass_reason or "Stage 0 bypass",
    )


def _apply_constraint(
    stage1: Stage1Result,
    gate: PreGateOutput,
) -> Stage1Result:
    """Apply Stage 0 constraint to Stage 1 result.

    Boosts scores for priority modes.
    """
    if not gate.priority_modes:
        return stage1

    priority_set = set(gate.priority_modes)

    # Boost priority modes
    for candidate in stage1.mode_candidates:
        if candidate.mode.value in priority_set:
            candidate.score = min(1.0, candidate.score + 0.2)

    # Re-sort by score
    stage1.mode_candidates.sort(key=lambda c: c.score, reverse=True)

    logger.info(
        f"Applied constraint: boosted {gate.priority_modes}, "
        f"top mode now {stage1.top_mode.value}"
    )

    return stage1


def _get_anchor_type(state: dict) -> Optional[str]:
    """Extract anchor type from state."""
    anchor = state.get("anchor")
    if anchor and hasattr(anchor, "type"):
        return anchor.type
    return None


def _get_anchor_id(state: dict) -> Optional[str]:
    """Extract anchor ID from state."""
    anchor = state.get("anchor")
    if anchor and hasattr(anchor, "id"):
        return anchor.id
    return None


# === LangGraph node interface ===

async def intent_router_node(state: "AgentState") -> dict[str, Any]:
    """LangGraph node for intent routing.

    Input: AgentState with event, anchor, draft, etc.
    Output: {"envelope": IntentEnvelope, ...}
    """
    from src.context.builder import build_context
    from src.context.spec import ContextSpec

    # Build input from state
    event = state.get("event", {})
    message = event.get("text", "")

    router_input = RouterInput(
        message=message,
        channel_id=event.get("channel_id", ""),
        thread_ts=event.get("thread_ts"),
        user_id=event.get("user_id"),
        is_command=event.get("is_command", False),
        command_name=event.get("command_name"),
        state=state,
    )

    # Build context using spec
    context_str = ""
    channel_id = event.get("channel_id", "")
    thread_ts = event.get("thread_ts")

    if channel_id and thread_ts:
        try:
            spec = ContextSpec.for_extraction(
                channel_id=channel_id,
                thread_ts=thread_ts,
            )
            context_packet = await build_context(spec)
            context_str = context_packet.to_prompt() if context_packet else ""
        except Exception as e:
            logger.warning(f"Context build failed, continuing without: {e}")

    # Route
    result = await route_intent(router_input, context=context_str)

    return {
        "envelope": result.envelope,
        "intent_result": result.envelope.to_legacy_intent_result(),  # Backward compat
        "stage1_mode": result.stage1_result.top_mode if result.stage1_result else None,
        "bypassed": result.bypassed,
    }
