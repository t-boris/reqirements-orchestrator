"""Ambiguity policy for intent classification (Phase 39).

Implements margin-based policy that decides when to return
kind=ambiguous instead of executing risky operations.

Thresholds from spec:
- margin < 0.15 -> ambiguous
- risk != safe AND confidence < 0.75 -> ambiguous
- conflicting targets -> ambiguous
"""
import logging
from dataclasses import dataclass
from typing import Optional

from src.schemas.intent_envelope import (
    IntentEnvelope,
    EnvelopeKind,
    RiskLevel,
    AmbiguousChoice,
    IntentCandidate,
)
from src.graph.intent_gates import check_risk_guard, GateResult, PreGateOutput

logger = logging.getLogger(__name__)


@dataclass
class PolicyConfig:
    """Configuration for ambiguity policy."""
    margin_threshold: float = 0.15
    confidence_threshold_risky: float = 0.75
    confidence_threshold_destructive: float = 0.85


DEFAULT_CONFIG = PolicyConfig()


def apply_ambiguity_policy(
    envelope: IntentEnvelope,
    config: PolicyConfig = DEFAULT_CONFIG,
) -> IntentEnvelope:
    """Apply ambiguity policy to IntentEnvelope.

    Converts single/plan to ambiguous if thresholds not met.

    Args:
        envelope: Original envelope from Stage 2
        config: Policy configuration

    Returns:
        Modified envelope (may be converted to ambiguous)
    """
    # Already ambiguous - nothing to do
    if envelope.kind == EnvelopeKind.AMBIGUOUS:
        return envelope

    # Check margin threshold
    if envelope.margin < config.margin_threshold:
        logger.info(
            f"Ambiguity policy: margin {envelope.margin:.2f} < {config.margin_threshold}"
        )
        return _convert_to_ambiguous(
            envelope,
            reason=f"Low margin ({envelope.margin:.2f}). Please clarify your intent.",
        )

    # Check confidence for risky operations
    if envelope.risk_level != RiskLevel.SAFE:
        threshold = (
            config.confidence_threshold_destructive
            if envelope.risk_level == RiskLevel.DESTRUCTIVE
            else config.confidence_threshold_risky
        )

        if envelope.confidence < threshold:
            logger.info(
                f"Ambiguity policy: confidence {envelope.confidence:.2f} < {threshold} "
                f"for {envelope.risk_level.value} operation"
            )
            return _convert_to_ambiguous(
                envelope,
                reason=f"This appears to be a {envelope.risk_level.value} operation. Please confirm.",
            )

    return envelope


def apply_risk_guard(
    envelope: IntentEnvelope,
    config: PolicyConfig = DEFAULT_CONFIG,
) -> IntentEnvelope:
    """Apply Stage 0 risk guard to envelope.

    Uses check_risk_guard from intent_gates to evaluate
    write/mass_write/destructive operations.

    Args:
        envelope: Envelope after Stage 2
        config: Policy configuration

    Returns:
        Modified envelope if guard triggers
    """
    if envelope.kind == EnvelopeKind.AMBIGUOUS:
        return envelope

    if envelope.kind == EnvelopeKind.SINGLE:
        guard = check_risk_guard(
            proposed_intent=envelope.intent.value if envelope.intent else "",
            proposed_risk=envelope.risk_level.value,
            confidence=envelope.confidence,
            margin=envelope.margin,
        )

        if guard and guard.result == GateResult.GUARD:
            logger.info(f"Risk guard triggered: {guard.guard_reason}")
            return _convert_to_ambiguous(envelope, reason=guard.guard_reason)

    elif envelope.kind == EnvelopeKind.PLAN:
        # Check if any task triggers guard
        for task in envelope.tasks:
            if task.risk_level in (RiskLevel.WRITE, RiskLevel.MASS_WRITE, RiskLevel.DESTRUCTIVE):
                guard = check_risk_guard(
                    proposed_intent=task.intent.value,
                    proposed_risk=task.risk_level.value,
                    confidence=envelope.confidence,
                    margin=envelope.margin,
                )
                if guard and guard.result == GateResult.GUARD:
                    logger.info(f"Risk guard on task: {guard.guard_reason}")
                    # Mark plan as requires_confirm instead of ambiguous
                    envelope.requires_confirm = True
                    break

    return envelope


def _convert_to_ambiguous(
    envelope: IntentEnvelope,
    reason: str,
) -> IntentEnvelope:
    """Convert single/plan envelope to ambiguous with choices.

    Builds choices from:
    1. Original intent (if single)
    2. Alternatives (if provided)
    3. Safe fallback option
    """
    choices = []

    if envelope.kind == EnvelopeKind.SINGLE and envelope.intent:
        # Original intent as first choice
        choices.append(AmbiguousChoice(
            label=_intent_to_label(envelope.intent.value),
            mode=envelope.mode,
            intent=envelope.intent,
            risk_level=envelope.risk_level,
            targets=envelope.targets,
            params=envelope.params,
        ))

        # Add alternatives
        for alt in envelope.alternatives[:2]:
            choices.append(AmbiguousChoice(
                label=_intent_to_label(alt.intent.value),
                mode=alt.mode,
                intent=alt.intent,
                risk_level=alt.risk_level,
                targets=alt.targets,
            ))

    elif envelope.kind == EnvelopeKind.PLAN:
        # Summarize plan as choice
        if envelope.tasks:
            choices.append(AmbiguousChoice(
                label=f"Execute {len(envelope.tasks)} tasks",
                mode=envelope.tasks[0].mode,
                intent=envelope.tasks[0].intent,
                risk_level=envelope.risk_level,
                params={"tasks": len(envelope.tasks)},
            ))

    # Always add safe fallback
    from src.schemas.intent import Intent, SuperMode
    choices.append(AmbiguousChoice(
        label="Just discuss",
        mode=SuperMode.CHAT,
        intent=Intent.DISCUSSION,
        risk_level=RiskLevel.SAFE,
    ))

    return IntentEnvelope.ambiguous(
        choices=choices[:4],  # Max 4 choices
        reason=reason,
        confidence=envelope.confidence,
        margin=envelope.margin,
    )


def _intent_to_label(intent_value: str) -> str:
    """Convert intent value to human-readable label."""
    labels = {
        "draft_refine": "Refine draft",
        "draft_transform": "Transform draft",
        "workitem_create": "Create work item",
        "review": "Review/analyze",
        "decision_record": "Record decision",
        "decision_update": "Update decision",
        "decision_link": "Link decision",
        "decision": "Record decision",
        "jira_command": "Jira command",
        "jira_search": "Search Jira",
        "sync_request": "Sync to Jira",
        "ticket_action": "Ticket action",
        "discussion": "Just discuss",
        "meta": "About the bot",
    }
    return labels.get(intent_value, intent_value.replace("_", " ").title())


def check_target_ambiguity(envelope: IntentEnvelope) -> Optional[str]:
    """Check if target is ambiguous (e.g., 'update this' without anchor).

    Returns reason string if ambiguous, None if targets are clear.
    """
    if envelope.kind != EnvelopeKind.SINGLE:
        return None

    # Check if intent requires target but none provided
    requires_target = envelope.intent and envelope.intent.value in (
        "jira_command",
        "ticket_action",
        "decision_update",
    )

    if not requires_target:
        return None

    targets = envelope.targets
    has_target = (
        targets.jira_key or
        targets.decision_id or
        targets.workitem_id
    )

    if not has_target:
        return "This action needs a target. Which item do you want to update?"

    return None
