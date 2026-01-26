"""Stage 0: Deterministic pre-gates for intent classification (Phase 39).

Pre-gates are state-based invariants applied BEFORE LLM classification.
They are NOT keyword pattern matching - they use state to:
1. Short-circuit to known intent (bypass LLM)
2. Constrain LLM to prioritize certain modes
3. Guard against risky operations
4. Triage incomplete contexts before classification

This is safety policy, not classification.
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING

from src.graph.triage_gate import check_triage_needed

if TYPE_CHECKING:
    from src.schemas.anchor import ThreadContext
    from src.schemas.state import AgentState
    from src.schemas.task_plan import TaskPlan
    from src.schemas.triage import TriageContext

logger = logging.getLogger(__name__)


class GateResult(str, Enum):
    """Result of pre-gate evaluation."""
    BYPASS = "bypass"      # Short-circuit: known intent, skip LLM
    CONSTRAIN = "constrain"  # Hint to LLM: prioritize certain modes
    GUARD = "guard"        # Risk guard: require confirmation
    TRIAGE = "triage"      # Needs triage questions before classification
    PASS = "pass"          # No gate triggered, proceed to LLM


@dataclass
class PreGateOutput:
    """Output from Stage 0 pre-gates."""
    result: GateResult
    # For BYPASS: the intent to use
    bypass_intent: Optional[str] = None
    bypass_mode: Optional[str] = None
    bypass_reason: Optional[str] = None
    # For CONSTRAIN: priority modes/intents
    priority_modes: list[str] = None
    constraint_reason: Optional[str] = None
    # For GUARD: what to guard against
    guard_reason: Optional[str] = None
    # For TRIAGE: context too incomplete
    triage_context: Optional["TriageContext"] = None

    def __post_init__(self):
        if self.priority_modes is None:
            self.priority_modes = []


def check_terminal_intent(
    message: str,
    is_command: bool,
    command_name: Optional[str] = None,
) -> Optional[PreGateOutput]:
    """Gate 1: Terminal handling.

    Known slash commands and terminal intents bypass classification.
    """
    # Known slash commands
    if is_command and command_name:
        cmd = command_name.lower()
        if cmd in ("help", "about", "version"):
            return PreGateOutput(
                result=GateResult.BYPASS,
                bypass_intent="meta",
                bypass_mode="chat",
                bypass_reason=f"Terminal command: /{cmd}",
            )
        if cmd in ("debug", "explain", "status"):
            return PreGateOutput(
                result=GateResult.BYPASS,
                bypass_intent="ops",
                bypass_mode="chat",
                bypass_reason=f"Ops command: /{cmd}",
            )
        if cmd == "sync":
            return PreGateOutput(
                result=GateResult.BYPASS,
                bypass_intent="sync_request",
                bypass_mode="operate",
                bypass_reason="Sync command",
            )

    return None


def check_taskplan_continuation(
    state: "AgentState",
    thread_ts: Optional[str],
) -> Optional[PreGateOutput]:
    """Gate 2: Active TaskPlan continuation.

    If there's an active TaskPlan that's BLOCKED and message is in
    same thread, this is an answer to a question - bypass classifier.
    """
    task_plan: Optional["TaskPlan"] = state.get("task_plan")
    if not task_plan:
        return None

    # Check if task plan is blocked waiting for answer
    if hasattr(task_plan, 'status'):
        status = task_plan.status
        if status == "blocked":
            # Check if same thread
            plan_thread = getattr(task_plan, 'source_thread_ts', None)
            if plan_thread and plan_thread == thread_ts:
                return PreGateOutput(
                    result=GateResult.BYPASS,
                    bypass_intent="answer_mapper",  # Route to AnswerMapper
                    bypass_mode="build",  # TaskPlan usually in BUILD mode
                    bypass_reason="TaskPlan BLOCKED, user reply is answer",
                )

    return None


def check_draft_priority(
    state: "AgentState",
    thread_ts: Optional[str],
) -> Optional[PreGateOutput]:
    """Gate 3: Draft priority gate.

    When active draft exists and message is in same thread/channel scope,
    LLM should prioritize BUILD intents over THINK/REVIEW.
    """
    draft = state.get("draft")
    structured_draft = state.get("structured_draft")

    has_draft = (
        (draft and hasattr(draft, 'title') and draft.title) or
        (structured_draft and hasattr(structured_draft, 'items') and structured_draft.items)
    )

    if not has_draft:
        return None

    # Draft exists - constrain LLM to prioritize BUILD
    return PreGateOutput(
        result=GateResult.CONSTRAIN,
        priority_modes=["build"],
        constraint_reason="Active draft exists - prioritize BUILD intents (DRAFT_REFINE, DRAFT_TRANSFORM)",
    )


def check_risk_guard(
    proposed_intent: str,
    proposed_risk: str,
    confidence: float,
    margin: float,
    threshold_margin: float = 0.15,
    threshold_confidence: float = 0.75,
) -> Optional[PreGateOutput]:
    """Gate 4: Risk guard.

    If proposed intent has write risk and confidence/margin is low,
    return ambiguous instead of executing.
    """
    # Only guard write/mass_write/destructive
    if proposed_risk not in ("write", "mass_write", "destructive"):
        return None

    # Check margin
    if margin < threshold_margin:
        return PreGateOutput(
            result=GateResult.GUARD,
            guard_reason=f"Low margin ({margin:.2f} < {threshold_margin}) for {proposed_risk} operation",
        )

    # Check confidence for risky operations
    if proposed_risk in ("mass_write", "destructive") and confidence < threshold_confidence:
        return PreGateOutput(
            result=GateResult.GUARD,
            guard_reason=f"Low confidence ({confidence:.2f}) for {proposed_risk} operation",
        )

    return None


def check_triage_gate(
    state: "AgentState",
    message: str,
    is_command: bool = False,
) -> Optional[PreGateOutput]:
    """Gate 0: Triage (completeness check).

    Check if context is complete enough for classification, or if we
    should ask clarifying questions first.

    Bypasses triage when:
    - is_command is True (slash commands bypass triage)
    - State already has triage_answers (prevent loops)
    - Message is short greeting (<5 words with no signals)

    Args:
        state: Current AgentState
        message: User's message text
        is_command: Whether message is a slash command

    Returns:
        PreGateOutput with TRIAGE result if incomplete, None to proceed.
    """
    # Slash commands bypass triage
    if is_command:
        logger.debug("Triage gate: skipped (slash command)")
        return None

    # Already has triage answers - prevent re-asking loops
    if state.get("triage_answers"):
        logger.debug("Triage gate: skipped (triage_answers already present)")
        return None

    # Check context completeness
    triage_context = check_triage_needed(state, message)

    # Fast path: context is complete enough
    if triage_context.fast_path:
        logger.debug(f"Triage gate: fast path (completeness={triage_context.completeness_score:.2f})")
        return None

    # Short greetings without signals should not trigger triage
    word_count = len(message.split())
    if word_count < 5 and not triage_context.signals:
        logger.debug("Triage gate: skipped (short greeting with no signals)")
        return None

    # Context incomplete - need triage questions
    return PreGateOutput(
        result=GateResult.TRIAGE,
        triage_context=triage_context,
    )


def run_pre_gates(
    message: str,
    state: "AgentState",
    is_command: bool = False,
    command_name: Optional[str] = None,
    thread_ts: Optional[str] = None,
) -> PreGateOutput:
    """Run all Stage 0 pre-gates in order.

    Gates are applied in priority order:
    0. Triage (completeness check - may need questions first)
    1. Terminal handling (commands, greetings)
    2. TaskPlan continuation (BLOCKED answer)
    3. Draft priority (constrain to BUILD)

    Note: Risk guard runs AFTER LLM classification, not in this pre-gate phase.

    Args:
        message: User's message text
        state: Current AgentState
        is_command: Whether message is a slash command
        command_name: Slash command name if applicable
        thread_ts: Thread timestamp for same-thread checks

    Returns:
        PreGateOutput with gate result
    """
    # Gate 0: Triage (completeness check)
    result = check_triage_gate(state, message, is_command)
    if result:
        logger.info(f"Pre-gate: triage needed - completeness={result.triage_context.completeness_score:.2f}")
        return result

    # Gate 1: Terminal handling
    result = check_terminal_intent(message, is_command, command_name)
    if result:
        logger.info(f"Pre-gate: terminal intent triggered - {result.bypass_reason}")
        return result

    # Gate 2: TaskPlan continuation
    result = check_taskplan_continuation(state, thread_ts)
    if result:
        logger.info(f"Pre-gate: taskplan continuation - {result.bypass_reason}")
        return result

    # Gate 3: Draft priority (this is CONSTRAIN, not BYPASS)
    result = check_draft_priority(state, thread_ts)
    if result:
        logger.info(f"Pre-gate: draft priority constraint - {result.constraint_reason}")
        return result

    # No gates triggered
    return PreGateOutput(result=GateResult.PASS)
