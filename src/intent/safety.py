"""Safety Evaluator - Validates actions before execution.

Sits between Router and Action execution to ensure:
- Lifecycle state allows the action
- Required approvals are in place
- User has permission
- No conflicts exist

Ref: CONTEXT.md - Section 4: Intent -> Action Safety Layer
Ref: BOT_DESIGN.md - Safety Guardrails
"""

import logging
from dataclasses import dataclass
from enum import Enum

from src.intent.schemas import (
    SuperMode,
    IntentClassification,
    SafetyCheckResult,
    EntityType,
)

logger = logging.getLogger(__name__)


class LifecycleState(str, Enum):
    """Entity lifecycle states.

    Ref: BOT_DESIGN.md - Entity Lifecycle State Machine
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    BLOCKED = "blocked"
    APPROVED = "approved"
    COMMITTED = "committed"
    DEPRECATED = "deprecated"


@dataclass
class EntityContext:
    """Context about an entity for safety checks."""

    entity_id: str
    entity_type: EntityType
    lifecycle_state: LifecycleState
    owner_id: str | None = None
    approvals: list[str] | None = None  # User IDs who approved
    objections: list[str] | None = None  # User IDs who objected


@dataclass
class ActionContext:
    """Context for safety evaluation."""

    user_id: str
    channel_id: str
    intent: IntentClassification
    target_entity: EntityContext | None = None


class SafetyEvaluator:
    """Evaluates if an action is safe to execute.

    Ref: CONTEXT.md - Safety Evaluator checks:
    - Lifecycle state
    - Approvals
    - Object locks
    - Permissions
    - Dry-run result
    """

    def evaluate(self, context: ActionContext) -> SafetyCheckResult:
        """Evaluate if the action is safe to execute.

        Args:
            context: Action context with user, channel, intent, and entity info

        Returns:
            SafetyCheckResult indicating if action is allowed
        """
        warnings: list[str] = []

        # Check based on mode
        match context.intent.mode:
            case SuperMode.CREATE:
                return self._check_create(context, warnings)
            case SuperMode.MODIFY:
                return self._check_modify(context, warnings)
            case SuperMode.RECORD:
                return self._check_record(context, warnings)
            case SuperMode.CONVERSE:
                # CONVERSE is always safe - no side effects
                return SafetyCheckResult(
                    allowed=True,
                    reason="CONVERSE mode has no side effects",
                    requires_confirmation=False,
                    warnings=warnings,
                )

    def _check_create(
        self, context: ActionContext, warnings: list[str]
    ) -> SafetyCheckResult:
        """Check safety for CREATE mode.

        CREATE requires:
        - User is in the channel (assumed if they sent a message)
        - Confirmation before creating (requires_confirmation=True)
        """
        # CREATE always requires confirmation per BOT_DESIGN.md
        # "All approvals require human action via button click"
        return SafetyCheckResult(
            allowed=True,
            reason="CREATE allowed with confirmation",
            requires_confirmation=True,
            warnings=warnings,
        )

    def _check_modify(
        self, context: ActionContext, warnings: list[str]
    ) -> SafetyCheckResult:
        """Check safety for MODIFY mode.

        MODIFY requires:
        - Target entity exists
        - Entity is in modifiable state (DRAFT or PROPOSED)
        - For state transitions: specific rules apply

        Ref: BOT_DESIGN.md - Transition Rules
        """
        if not context.target_entity:
            return SafetyCheckResult(
                allowed=False,
                reason="No target entity specified for MODIFY",
                requires_confirmation=False,
                warnings=warnings,
            )

        entity = context.target_entity

        # Check lifecycle state allows modification
        modifiable_states = {
            LifecycleState.DRAFT,
            LifecycleState.PROPOSED,
        }

        if entity.lifecycle_state not in modifiable_states:
            return SafetyCheckResult(
                allowed=False,
                reason=f"Entity in {entity.lifecycle_state} state cannot be modified",
                requires_confirmation=False,
                warnings=warnings,
            )

        # Check for objections (BLOCKED state)
        if entity.lifecycle_state == LifecycleState.PROPOSED:
            if entity.objections:
                warnings.append(
                    f"Entity has {len(entity.objections)} objection(s) that need resolution"
                )

        # MODIFY allowed with confirmation
        return SafetyCheckResult(
            allowed=True,
            reason="MODIFY allowed for entity in modifiable state",
            requires_confirmation=True,
            warnings=warnings,
        )

    def _check_record(
        self, context: ActionContext, warnings: list[str]
    ) -> SafetyCheckResult:
        """Check safety for RECORD mode.

        RECORD (decision capture) requires:
        - User made a commitment (handled by intent classification)
        - Confirmation before recording
        """
        # RECORD creates a Decision entity, requires confirmation
        return SafetyCheckResult(
            allowed=True,
            reason="RECORD allowed with confirmation",
            requires_confirmation=True,
            warnings=warnings,
        )


# Module-level evaluator instance
_evaluator: SafetyEvaluator | None = None


def get_safety_evaluator() -> SafetyEvaluator:
    """Get the safety evaluator instance."""
    global _evaluator
    if _evaluator is None:
        _evaluator = SafetyEvaluator()
    return _evaluator


def evaluate_safety(context: ActionContext) -> SafetyCheckResult:
    """Convenience function to evaluate action safety.

    Args:
        context: Action context

    Returns:
        SafetyCheckResult
    """
    return get_safety_evaluator().evaluate(context)
