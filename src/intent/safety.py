"""Safety evaluator for intent actions.

Determines whether an action is allowed based on:
- User permissions
- Entity lifecycle state
- Mode-specific rules

Ref: BOT_DESIGN.md - Safety Guardrails
"""

from dataclasses import dataclass
from typing import Any

from src.domain.entities import (
    ApprovedEntity,
    CommittedEntity,
    DeprecatedEntity,
    DraftEntity,
    Entity,
    ProposedEntity,
    get_lifecycle,
)
from src.domain.transitions import can_approve, can_commit, can_modify
from src.domain.types import EntityLifecycle
from src.intent.schemas import IntentClassification, SafetyCheckResult, SuperMode


@dataclass
class ActionContext:
    """Context for safety evaluation."""

    user_id: str
    channel_id: str
    intent: IntentClassification
    target_entity: Entity | None = None


def evaluate_safety(context: ActionContext) -> SafetyCheckResult:
    """Evaluate whether an action is safe to perform.

    Args:
        context: Action context with user, channel, intent, and target entity

    Returns:
        SafetyCheckResult with allowed status and any restrictions
    """
    mode = context.intent.mode

    # CONVERSE mode is always allowed (no side effects)
    if mode == SuperMode.CONVERSE:
        return SafetyCheckResult(
            allowed=True,
            requires_confirmation=False,
        )

    # CREATE mode - always requires confirmation
    if mode == SuperMode.CREATE:
        return SafetyCheckResult(
            allowed=True,
            requires_confirmation=True,
            confirmation_prompt="Create this entity?",
        )

    # RECORD mode - always requires confirmation
    if mode == SuperMode.RECORD:
        return SafetyCheckResult(
            allowed=True,
            requires_confirmation=True,
            confirmation_prompt="Record this decision?",
        )

    # MODIFY mode - check entity lifecycle
    if mode == SuperMode.MODIFY:
        return _evaluate_modify_safety(context)

    # Unknown mode - deny
    return SafetyCheckResult(
        allowed=False,
        reason=f"Unknown mode: {mode}",
    )


def _evaluate_modify_safety(context: ActionContext) -> SafetyCheckResult:
    """Evaluate safety for MODIFY mode.

    Per BOT_DESIGN.md: Only DRAFT and PROPOSED entities can be modified.
    """
    entity = context.target_entity

    # No target entity specified
    if not entity:
        return SafetyCheckResult(
            allowed=True,
            requires_confirmation=True,
            confirmation_prompt="Which entity do you want to modify?",
        )

    # Check lifecycle allows modification
    can_mod, reason = can_modify(entity)

    if not can_mod:
        lifecycle = get_lifecycle(entity)
        return SafetyCheckResult(
            allowed=False,
            reason=f"Cannot modify entity in {lifecycle.value} state. {reason}",
        )

    # Entity can be modified - require confirmation
    return SafetyCheckResult(
        allowed=True,
        requires_confirmation=True,
        confirmation_prompt="Apply these changes?",
    )


def evaluate_approval_safety(
    entity: Entity,
    user_id: str,
) -> SafetyCheckResult:
    """Evaluate safety for approval action.

    Args:
        entity: Entity to approve
        user_id: User attempting approval

    Returns:
        SafetyCheckResult
    """
    can_app, reason = can_approve(entity)

    if not can_app:
        return SafetyCheckResult(
            allowed=False,
            reason=reason,
        )

    # Check if user already approved
    if isinstance(entity, ProposedEntity):
        if any(a.user_id == user_id for a in entity.approvals):
            return SafetyCheckResult(
                allowed=False,
                reason="You have already approved this entity",
            )

    return SafetyCheckResult(
        allowed=True,
        requires_confirmation=False,  # Button click is the confirmation
    )


def evaluate_commit_safety(
    entity: Entity,
    user_id: str,
) -> SafetyCheckResult:
    """Evaluate safety for commit action.

    Args:
        entity: Entity to commit
        user_id: User attempting commit

    Returns:
        SafetyCheckResult
    """
    can_com, reason = can_commit(entity)

    if not can_com:
        return SafetyCheckResult(
            allowed=False,
            reason=reason,
        )

    return SafetyCheckResult(
        allowed=True,
        requires_confirmation=True,
        confirmation_prompt="Sync this entity to Jira?",
    )


def evaluate_objection_safety(
    entity: Entity,
    user_id: str,
) -> SafetyCheckResult:
    """Evaluate safety for objection action.

    Args:
        entity: Entity to object to
        user_id: User raising objection

    Returns:
        SafetyCheckResult
    """
    if not isinstance(entity, ProposedEntity):
        lifecycle = get_lifecycle(entity)
        return SafetyCheckResult(
            allowed=False,
            reason=f"Cannot object to entity in {lifecycle.value} state",
        )

    return SafetyCheckResult(
        allowed=True,
        requires_confirmation=False,  # Button click triggers modal for reason
    )
